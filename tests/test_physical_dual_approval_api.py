import json
import time
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from rarelink.api import main as api_main
from rarelink.api.main import app
from rarelink.config import Settings, get_settings
from rarelink.database import get_session
from rarelink.domain import PhysicalJobStatus, PhysicalSiteStatus, utc_now
from rarelink.models import PhysicalFederationJob, PhysicalJobApprovalRecord, PhysicalSite
from rarelink.services.physical_approval import canonical_contract_sha256
from rarelink.services.physical_controller import (
    CommandResult,
    NvflareCliAdapter,
    PhysicalFederationController,
)
from rarelink.services.physical_store import SqlPhysicalJobStore

ISSUER = "https://identity.hospital.example"
AUDIENCE = "rarelink-physical-control"


def oidc_material() -> tuple[Any, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(
        private_key.public_key(),
        as_dict=True,
    )
    jwk.update({"kid": "hospital-key-1", "alg": "RS256", "use": "sig"})
    return private_key, jwk


def oidc_token(
    private_key: Any,
    *,
    subject: str,
    roles: list[str],
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": subject,
            "exp": now + 300,
            "iat": now - 5,
            "roles": roles,
            "organization": "hospital-research",
            "site_ids": [],
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "hospital-key-1"},
    )


def physical_oidc_settings(jwk: dict[str, Any]) -> Settings:
    return Settings(
        _env_file=None,
        rarelink_allow_llm=False,
        rarelink_physical_mode="physical",
        rarelink_physical_auth_mode="oidc",
        rarelink_audit_hmac_key="audit-key-for-dual-approval-tests-0001",
        rarelink_oidc_issuer=ISSUER,
        rarelink_oidc_audience=AUDIENCE,
        rarelink_oidc_jwks_json=json.dumps({"keys": [jwk]}),
    )


def with_test_session() -> tuple[Session, Any]:
    provider = app.dependency_overrides[get_session]
    generator = provider()
    return next(generator), generator


def insert_proposed_job(subject: str) -> str:
    session, generator = with_test_session()
    try:
        job = PhysicalFederationJob(
            study_id="study-physical-001",
            strategy="fedavg",
            status=PhysicalJobStatus.APPROVAL_PENDING,
            bundle_sha256="d" * 64,
            expected_sites_json=json.dumps(
                ["hospital-a", "hospital-b", "hospital-c"]
            ),
            dataset_fingerprints_json=json.dumps(
                {
                    "hospital-a": "a" * 64,
                    "hospital-b": "b" * 64,
                    "hospital-c": "c" * 64,
                }
            ),
            total_rounds=5,
            local_epochs=1,
            quorum_required=3,
            job_directory="/coordinator-only/not-returned",
            proposed_by=subject,
            proposer_roles_json=json.dumps(["research_lead"]),
        )
        job.contract_sha256 = canonical_contract_sha256(job)
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.id
    finally:
        session.close()
        generator.close()


def mutate_job_rounds(job_id: str, rounds: int) -> None:
    session, generator = with_test_session()
    try:
        job = session.get(PhysicalFederationJob, job_id)
        assert job is not None
        job.total_rounds = rounds
        session.add(job)
        session.commit()
    finally:
        session.close()
        generator.close()


def assert_approval_note_is_digest_only(job_id: str, raw_note: str) -> None:
    session, generator = with_test_session()
    try:
        record = session.exec(
            select(PhysicalJobApprovalRecord).where(
                PhysicalJobApprovalRecord.job_id == job_id
            )
        ).one()
        job = session.get(PhysicalFederationJob, job_id)
        assert job is not None
        assert len(record.note_sha256) == 64
        assert record.note_sha256 != raw_note
        assert job.second_approval_note_sha256 == record.note_sha256
        assert raw_note not in record.model_dump_json()
        assert raw_note not in job.model_dump_json()
    finally:
        session.close()
        generator.close()


def insert_ready_sites() -> None:
    session, generator = with_test_session()
    try:
        for suffix in ("a", "b", "c"):
            session.add(
                PhysicalSite(
                    site_id=f"hospital-{suffix}",
                    display_name=f"Hospital {suffix.upper()} Spark",
                    organization=f"hospital_{suffix}",
                    status=PhysicalSiteStatus.READY,
                    certificate_status="VALID",
                    data_ready=True,
                    gpu_ready=True,
                    monai_ready=True,
                    nvflare_ready=True,
                    dataset_fingerprint=suffix * 64,
                    receipt_sha256="f" * 64,
                    last_heartbeat_at=utc_now(),
                )
            )
        session.commit()
    finally:
        session.close()
        generator.close()


def submit_payload() -> dict[str, str]:
    return {
        "approved_by": "ignored-body-identity",
        "note": "Submission after independent approval",
        "submit_token": "submission-token-001",
    }


def test_physical_contract_requires_distinct_persisted_second_approval(
    client: TestClient,
) -> None:
    private_key, jwk = oidc_material()
    app.dependency_overrides[get_settings] = lambda: physical_oidc_settings(jwk)
    lead = oidc_token(
        private_key,
        subject="lead-subject",
        roles=["research_lead"],
    )
    reviewer = oidc_token(
        private_key,
        subject="reviewer-subject",
        roles=["reviewer"],
    )
    other_reviewer = oidc_token(
        private_key,
        subject="other-reviewer-subject",
        roles=["reviewer"],
    )
    job_id = insert_proposed_job("lead-subject")

    before_approval = client.post(
        f"/api/physical/jobs/{job_id}:submit",
        headers={"Authorization": f"Bearer {lead}"},
        json=submit_payload(),
    )
    assert before_approval.status_code == 409
    assert "distinct second" in before_approval.json()["detail"]

    self_approval = client.post(
        f"/api/physical/jobs/{job_id}:approve",
        headers={"Authorization": f"Bearer {lead}"},
        json={
            "attestation": "CONTRACT_DATA_AND_SECURITY_REVIEWED",
            "note": "Must be rejected because this is the proposer",
        },
    )
    assert self_approval.status_code == 409
    assert "distinct subjects" in self_approval.json()["detail"]

    approval_note = "Independent data, protocol, and security review completed"
    approved = client.post(
        f"/api/physical/jobs/{job_id}:approve",
        headers={"Authorization": f"Bearer {reviewer}"},
        json={
            "attestation": "CONTRACT_DATA_AND_SECURITY_REVIEWED",
            "note": approval_note,
        },
    )
    assert approved.status_code == 200
    assert approved.json()["approval_count"] == 2
    assert approved.json()["approval_required"] == 2
    assert approved.json()["approval_state"] == "SECOND_APPROVAL_RECORDED"
    assert approved.json()["contract_sha256"]
    assert "lead-subject" not in approved.text
    assert "reviewer-subject" not in approved.text
    assert "coordinator-only" not in approved.text
    assert_approval_note_is_digest_only(job_id, approval_note)

    events = client.get(
        "/api/physical/events",
        headers={"Authorization": f"Bearer {reviewer}"},
    )
    assert events.status_code == 200
    assert events.json()["verified"] is True
    assert events.json()["event_count"] == 1
    assert events.json()["events"][0]["action"] == "job.contract-second-approved"
    assert "submission-token-001" not in events.text
    assert "Independent data" not in events.text

    repeated = client.post(
        f"/api/physical/jobs/{job_id}:approve",
        headers={"Authorization": f"Bearer {reviewer}"},
        json={
            "attestation": "CONTRACT_DATA_AND_SECURITY_REVIEWED",
            "note": "A repeat request is idempotent",
        },
    )
    assert repeated.status_code == 200
    repeated_events = client.get(
        "/api/physical/events",
        headers={"Authorization": f"Bearer {reviewer}"},
    )
    assert repeated_events.json()["event_count"] == 1

    conflicting = client.post(
        f"/api/physical/jobs/{job_id}:approve",
        headers={"Authorization": f"Bearer {other_reviewer}"},
        json={
            "attestation": "CONTRACT_DATA_AND_SECURITY_REVIEWED",
            "note": "A second competing approval must conflict",
        },
    )
    assert conflicting.status_code == 409

    mutate_job_rounds(job_id, 6)
    stale_repeat = client.post(
        f"/api/physical/jobs/{job_id}:approve",
        headers={"Authorization": f"Bearer {reviewer}"},
        json={
            "attestation": "CONTRACT_DATA_AND_SECURITY_REVIEWED",
            "note": "A stale approval must not remain idempotent",
        },
    )
    assert stale_repeat.status_code == 409
    assert "changed after proposal" in stale_repeat.json()["detail"]
    changed_contract = client.post(
        f"/api/physical/jobs/{job_id}:submit",
        headers={"Authorization": f"Bearer {lead}"},
        json=submit_payload(),
    )
    assert changed_contract.status_code == 409
    assert "changed after proposal" in changed_contract.json()["detail"]
    assert lead not in changed_contract.text


def test_distinct_approval_allows_real_controller_submission_boundary(
    client: TestClient,
    monkeypatch,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    private_key, jwk = oidc_material()
    app.dependency_overrides[get_settings] = lambda: physical_oidc_settings(jwk)
    lead = oidc_token(
        private_key,
        subject="lead-subject",
        roles=["research_lead"],
    )
    reviewer = oidc_token(
        private_key,
        subject="reviewer-subject",
        roles=["reviewer"],
    )
    insert_ready_sites()
    job_id = insert_proposed_job("lead-subject")
    approved = client.post(
        f"/api/physical/jobs/{job_id}:approve",
        headers={"Authorization": f"Bearer {reviewer}"},
        json={
            "attestation": "CONTRACT_DATA_AND_SECURITY_REVIEWED",
            "note": "Independent contract review completed",
        },
    )
    assert approved.status_code == 200

    commands: list[list[str]] = []

    def runner(command):  # type: ignore[no-untyped-def]
        commands.append(list(command))
        return CommandResult(0, '{"job_id":"flare-dual-approved-001"}')

    def controller_factory(session, _config):  # type: ignore[no-untyped-def]
        return (
            PhysicalFederationController(
                NvflareCliAdapter(runner=runner),
                SqlPhysicalJobStore(session),
            ),
            tmp_path / "admin-kit",
        )

    monkeypatch.setattr(api_main, "build_physical_controller", controller_factory)
    submitted = client.post(
        f"/api/physical/jobs/{job_id}:submit",
        headers={"Authorization": f"Bearer {lead}"},
        json=submit_payload(),
    )

    assert submitted.status_code == 200
    assert submitted.json()["status"] == "SUBMITTED"
    assert submitted.json()["external_job_id"] == "flare-dual-approved-001"
    assert submitted.json()["approval_count"] == 2
    assert len(commands) == 1
    assert "submission-token-001" not in " ".join(commands[0])
    assert "lead-subject" not in submitted.text
    assert "reviewer-subject" not in submitted.text

    events = client.get(
        "/api/physical/events",
        headers={"Authorization": f"Bearer {reviewer}"},
    ).json()
    assert events["verified"] is True
    assert [event["action"] for event in events["events"]] == [
        "job.contract-second-approved",
        "job.submitted",
    ]
    assert events["events"][1]["payload"]["approval_count"] == 2
