import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from rarelink.api import main as api_main
from rarelink.api.main import app
from rarelink.config import Settings, get_settings
from rarelink.domain import PhysicalSiteHeartbeat
from rarelink.security import heartbeat_signature
from rarelink.services.physical_controller import (
    CommandResult,
    NvflareCliAdapter,
    PhysicalFederationController,
)
from rarelink.services.physical_store import SqlPhysicalJobStore

OPERATOR_HEADERS = {"X-RareLink-Operator-Token": "operator-secret"}
SITE_SECRETS = {
    "hospital-a": "site-secret-a",
    "hospital-b": "site-secret-b",
    "hospital-c": "site-secret-c",
}


def register_sites(client: TestClient) -> None:
    for suffix in ("a", "b", "c"):
        response = client.post(
            "/api/physical/sites",
            json={
                "site_id": f"hospital-{suffix}",
                "display_name": f"Hospital {suffix.upper()} Spark",
                "organization": f"hospital_{suffix}",
            },
            headers=OPERATOR_HEADERS,
        )
        assert response.status_code == 201


def send_ready_heartbeat(
    client: TestClient,
    site_id: str,
    *,
    sequence: int = 1,
    dataset_fingerprint: str | None = None,
) -> None:
    payload = PhysicalSiteHeartbeat(
        heartbeat_id=f"heartbeat-{site_id}-{sequence:04d}",
        agent_version="0.2.0",
        status="READY",
        certificate_status="VALID",
        data_ready=True,
        gpu_ready=True,
        monai_ready=True,
        nvflare_ready=True,
        free_memory_percent=67.5,
        free_disk_percent=80.0,
        dataset_fingerprint=dataset_fingerprint or (site_id[-1] * 64),
        receipt_sha256="f" * 64,
        captured_at=datetime.now(UTC),
    )
    timestamp = int(time.time())
    body = payload.model_dump(mode="json")
    signature = heartbeat_signature(
        site_id,
        timestamp,
        payload.heartbeat_id,
        body,
        SITE_SECRETS[site_id],
    )
    response = client.post(
        f"/api/physical/sites/{site_id}/heartbeat",
        json=body,
        headers={
            "X-RareLink-Site-Timestamp": str(timestamp),
            "X-RareLink-Site-Signature": signature,
        },
    )
    assert response.status_code == 200


def ready_sites(client: TestClient) -> None:
    for suffix in ("a", "b", "c"):
        send_ready_heartbeat(client, f"hospital-{suffix}")


def exported_job(tmp_path: Path) -> Path:
    root = tmp_path / "physical-fedavg"
    root.mkdir()
    (root / "meta.json").write_text(
        json.dumps({"name": "rarelink-physical-fedavg"}),
        encoding="utf-8",
    )
    (root / "rarelink-job-receipt.json").write_text(
        json.dumps(
            {
                "strategy": "fedavg",
                "rounds": 5,
                "local_epochs": 1,
                "expected_sites": ["hospital-a", "hospital-b", "hospital-c"],
                "local_only_manifest_required": True,
                "dataset_receipt_required": True,
                "patient_data_packaged": False,
                "certificates_packaged": False,
                "private_keys_packaged": False,
            }
        ),
        encoding="utf-8",
    )
    return root


def test_physical_registry_accepts_authenticated_patient_free_heartbeat(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        rarelink_allow_llm=False,
        rarelink_physical_mode="isolated-integration",
        rarelink_physical_site_secrets='{"hospital-a":"site-secret"}',
        rarelink_physical_operator_token="operator-secret",
    )
    register_sites(client)
    payload = PhysicalSiteHeartbeat(
        heartbeat_id="heartbeat-0001",
        agent_version="0.2.0",
        status="READY",
        certificate_status="VALID",
        data_ready=True,
        gpu_ready=True,
        monai_ready=True,
        nvflare_ready=True,
        free_memory_percent=67.5,
        free_disk_percent=80.0,
        dataset_fingerprint="a" * 64,
        receipt_sha256="a" * 64,
        captured_at=datetime.now(UTC),
    )
    timestamp = int(time.time())
    body = payload.model_dump(mode="json")
    signature = heartbeat_signature(
        "hospital-a",
        timestamp,
        payload.heartbeat_id,
        body,
        "site-secret",
    )

    accepted = client.post(
        "/api/physical/sites/hospital-a/heartbeat",
        json=body,
        headers={
            "X-RareLink-Site-Timestamp": str(timestamp),
            "X-RareLink-Site-Signature": signature,
        },
    )

    assert accepted.status_code == 200
    assert accepted.json()["status"] == "READY"
    assert accepted.json()["contains_patient_data"] is False
    assert "site-secret" not in accepted.text
    duplicate = client.post(
        "/api/physical/sites/hospital-a/heartbeat",
        json=body,
        headers={
            "X-RareLink-Site-Timestamp": str(timestamp),
            "X-RareLink-Site-Signature": signature,
        },
    )
    assert duplicate.status_code == 409

    stale = payload.model_copy(
        update={
            "heartbeat_id": "heartbeat-stale-0002",
            "captured_at": datetime.now(UTC) - timedelta(hours=1),
        }
    )
    stale_body = stale.model_dump(mode="json")
    stale_signature = heartbeat_signature(
        "hospital-a",
        timestamp,
        stale.heartbeat_id,
        stale_body,
        "site-secret",
    )
    rejected = client.post(
        "/api/physical/sites/hospital-a/heartbeat",
        json=stale_body,
        headers={
            "X-RareLink-Site-Timestamp": str(timestamp),
            "X-RareLink-Site-Signature": stale_signature,
        },
    )
    assert rejected.status_code == 401
    assert "replay window" in rejected.json()["detail"]


def test_physical_job_requires_three_registered_unique_sites(
    client: TestClient,
    tmp_path: Path,
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        rarelink_allow_llm=False,
        rarelink_physical_mode="isolated-integration",
        rarelink_physical_operator_token="operator-secret",
        rarelink_physical_site_secrets=json.dumps(SITE_SECRETS),
    )
    register_sites(client)
    ready_sites(client)
    created = client.post(
        "/api/physical/jobs",
        json={
            "strategy": "fedavg",
            "expected_sites": ["hospital-a", "hospital-b", "hospital-c"],
            "total_rounds": 5,
            "local_epochs": 1,
            "job_directory": str(exported_job(tmp_path)),
        },
        headers=OPERATOR_HEADERS,
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["status"] == "APPROVAL_PENDING"
    assert payload["quorum_required"] == 3
    assert payload["external_job_id"] is None
    assert payload["dataset_fingerprints"] == {
        "hospital-a": "a" * 64,
        "hospital-b": "b" * 64,
        "hospital-c": "c" * 64,
    }

    invalid = client.post(
        "/api/physical/jobs",
        json={
            "strategy": "fedavg",
            "expected_sites": ["hospital-a", "hospital-a", "hospital-c"],
            "total_rounds": 5,
            "job_directory": "/var/lib/rarelink/jobs/invalid",
        },
        headers=OPERATOR_HEADERS,
    )
    assert invalid.status_code == 422


def test_physical_mutations_are_closed_when_operator_identity_is_unconfigured(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/physical/sites",
        json={
            "site_id": "hospital-a",
            "display_name": "Hospital A Spark",
            "organization": "hospital_a",
        },
    )

    assert response.status_code == 503


def test_approved_physical_job_persists_real_external_job_id(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        rarelink_allow_llm=False,
        rarelink_physical_mode="isolated-integration",
        rarelink_physical_operator_token="operator-secret",
        rarelink_physical_site_secrets=json.dumps(SITE_SECRETS),
    )
    register_sites(client)
    ready_sites(client)
    created = client.post(
        "/api/physical/jobs",
        headers=OPERATOR_HEADERS,
        json={
            "strategy": "fedavg",
            "expected_sites": ["hospital-a", "hospital-b", "hospital-c"],
            "total_rounds": 5,
            "local_epochs": 1,
            "job_directory": str(exported_job(tmp_path)),
        },
    )
    assert created.status_code == 201
    job_id = created.json()["id"]
    commands: list[list[str]] = []

    def runner(command):  # type: ignore[no-untyped-def]
        commands.append(list(command))
        return CommandResult(0, '{"job_id":"flare-real-001"}')

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
        headers=OPERATOR_HEADERS,
        json={
            "approved_by": "Research PI",
            "note": "Three-site contract and bundle hash reviewed",
            "submit_token": "submission-token-001",
        },
    )

    assert submitted.status_code == 200
    assert submitted.json()["external_job_id"] == "flare-real-001"
    assert submitted.json()["status"] == "SUBMITTED"
    assert len(commands) == 1
    assert "submission-token-001" not in " ".join(commands[0])


def test_physical_job_is_invalidated_when_a_site_dataset_version_changes(
    client: TestClient,
    tmp_path: Path,
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        rarelink_allow_llm=False,
        rarelink_physical_mode="isolated-integration",
        rarelink_physical_operator_token="operator-secret",
        rarelink_physical_site_secrets=json.dumps(SITE_SECRETS),
    )
    register_sites(client)
    ready_sites(client)
    created = client.post(
        "/api/physical/jobs",
        headers=OPERATOR_HEADERS,
        json={
            "strategy": "fedavg",
            "expected_sites": ["hospital-a", "hospital-b", "hospital-c"],
            "total_rounds": 5,
            "local_epochs": 1,
            "job_directory": str(exported_job(tmp_path)),
        },
    )
    assert created.status_code == 201

    send_ready_heartbeat(
        client,
        "hospital-a",
        sequence=2,
        dataset_fingerprint="d" * 64,
    )
    jobs = client.get("/api/physical/jobs").json()
    assert jobs[0]["status"] == "FAILED"
    assert jobs[0]["error"] == "DATASET_VERSION_CHANGED"


def test_model_verification_route_never_exposes_coordinator_path(
    client: TestClient,
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        rarelink_allow_llm=False,
        rarelink_physical_mode="isolated-integration",
        rarelink_physical_operator_token="operator-secret",
    )
    model = tmp_path / "private-coordinator-store" / "global-model.pt"
    model.parent.mkdir()
    model.write_bytes(b"global-model")
    expected = "c" * 64

    class Verifier:
        def verify_global_model(
            self,
            job_id: str,
            model_path: Path,
            *,
            expected_sha256: str,
        ) -> dict:
            assert job_id == "physical-job-001"
            assert model_path == model
            assert expected_sha256 == expected
            return {
                "job_id": job_id,
                "model_file_name": model_path.name,
                "global_model_sha256": expected_sha256,
                "verified": True,
                "model_path_exported": False,
                "patient_data_exported": False,
            }

    monkeypatch.setattr(
        api_main,
        "build_physical_controller",
        lambda _session, _config: (Verifier(), tmp_path / "admin-kit"),
    )
    response = client.post(
        "/api/physical/jobs/physical-job-001:verify-model",
        headers=OPERATOR_HEADERS,
        json={"model_path": str(model), "expected_sha256": expected},
    )

    assert response.status_code == 200
    assert response.json()["verified"] is True
    assert str(model.parent) not in response.text
