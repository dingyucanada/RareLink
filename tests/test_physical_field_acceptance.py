from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from rarelink.deployment.field_acceptance import (
    FieldAcceptanceCredentials,
    PhysicalFieldAcceptanceError,
    PhysicalFieldAcceptancePlan,
    run_physical_field_acceptance,
)

SITES = ("hospital-a", "hospital-b", "hospital-c")
CONTRACT = "a" * 64
MODEL = "b" * 64


class FakeTransport:
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.headers: list[dict[str, str]] = []

    def get_json(self, url: str, *, headers: dict[str, str]) -> Any:
        self.headers.append(headers)
        if url not in self.responses:
            raise AssertionError(f"Unexpected field URL: {url}")
        return self.responses[url]


def plan(**overrides: object) -> PhysicalFieldAcceptancePlan:
    values: dict[str, object] = {
        "schema_version": "rarelink-physical-field-acceptance-plan-v1",
        "coordinator_base_url": "http://127.0.0.1:8000",
        "sites": [
            {
                "site_id": site,
                "base_url": f"http://127.0.0.1:{9100 + index}",
            }
            for index, site in enumerate(SITES)
        ],
        "job_id": "physical-job-001",
        "contract_sha256": CONTRACT,
        "expected_rounds": 5,
        "quorum_required": 3,
        "require_completed_job": False,
        "require_clients_connected": True,
        "requested_evidence_level": "L2",
        "allow_loopback_http": True,
    }
    values.update(overrides)
    return PhysicalFieldAcceptancePlan.model_validate(values)


def healthy() -> dict[str, object]:
    return {
        "ready": True,
        "checks": {
            name: {"ok": True, "status": "ready"}
            for name in (
                "gpu",
                "memory",
                "disk",
                "certificate",
                "dependencies",
                "dataset_manifest",
            )
        },
    }


def responses(*, completed: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for index, _site in enumerate(SITES):
        base = f"http://127.0.0.1:{9100 + index}"
        result[f"{base}/v1/site/ready"] = healthy()
        result[f"{base}/v1/tasks"] = [
            {
                "task_id": "physical-job-001",
                "round_id": 5 if completed else 2,
                "state": "COMPLETED" if completed else "RUNNING",
                "receipt": {"receipt_sha256": str(index + 1) * 64},
            }
        ]
    coordinator = "http://127.0.0.1:8000"
    result[f"{coordinator}/api/physical/sites"] = [
        {
            "site_id": site,
            "deployment_mode": "physical",
            "status": "READY" if completed else "TRAINING",
            "certificate_status": "VALID",
            "data_ready": True,
            "gpu_ready": True,
            "monai_ready": True,
            "nvflare_ready": True,
        }
        for site in SITES
    ]
    result[f"{coordinator}/api/physical/jobs"] = [
        {
            "id": "physical-job-001",
            "deployment_mode": "physical",
            "external_job_id": "nvflare-job-001",
            "status": "COMPLETED" if completed else "RUNNING",
            "contract_sha256": CONTRACT,
            "expected_sites": list(SITES),
            "total_rounds": 5,
            "current_round": 5 if completed else 2,
            "received_updates": 3 if completed else 2,
            "quorum_required": 3,
            "global_model_sha256": MODEL if completed else None,
            "model_release": {"algorithm": "Ed25519"} if completed else None,
        }
    ]
    result[f"{coordinator}/api/physical/audit-summary"] = {
        "verified": True,
        "head_event_hash": "c" * 64,
        "contains_patient_data": False,
        "contains_secret": False,
    }
    result[f"{coordinator}/api/physical/jobs/physical-job-001/clients"] = {
        "connected_sites": list(SITES),
        "all_expected_connected": True,
    }
    if completed:
        result[
            f"{coordinator}/api/physical/jobs/physical-job-001/review-readiness"
        ] = {"ready_for_statistical_review": True}
    return result


def credentials() -> FieldAcceptanceCredentials:
    return FieldAcceptanceCredentials(
        coordinator_bearer_token="coordinator-token-value-000000",
        site_bearer_tokens={
            site: f"site-token-value-{site}-000000" for site in SITES
        },
    )


def test_read_only_field_acceptance_emits_deidentified_l2_receipt() -> None:
    transport = FakeTransport(responses())

    receipt = run_physical_field_acceptance(
        plan(),
        credentials=credentials(),
        transport=transport,
    )

    assert receipt["passed"] is True
    assert receipt["achieved_evidence_level"] == "L2"
    assert receipt["read_only_collection"] is True
    assert len(receipt["site_receipts"]) == 3
    assert receipt["coordinator"]["connected_sites"] == list(SITES)
    rendered = str(receipt)
    assert "http://127.0.0.1" not in rendered
    assert "token-value" not in rendered
    assert all("Authorization" in headers for headers in transport.headers)


def test_completed_job_requires_model_release_and_review_gate() -> None:
    receipt = run_physical_field_acceptance(
        plan(require_completed_job=True, expected_model_sha256=MODEL),
        credentials=credentials(),
        transport=FakeTransport(responses(completed=True)),
    )

    assert receipt["coordinator"]["job_status"] == "COMPLETED"
    assert receipt["coordinator"]["review_ready"] is True


def test_field_acceptance_fails_closed_on_site_health_error() -> None:
    unsafe = responses()
    unsafe["http://127.0.0.1:9101/v1/site/ready"]["checks"]["disk"]["ok"] = False

    with pytest.raises(PhysicalFieldAcceptanceError, match="health check"):
        run_physical_field_acceptance(
            plan(),
            credentials=credentials(),
            transport=FakeTransport(unsafe),
        )


def test_l3_candidate_requires_https_distinct_attestations() -> None:
    l3 = {
        "schema_version": "rarelink-physical-field-acceptance-plan-v1",
        "coordinator_base_url": "https://coordinator.example",
        "sites": [
            {
                "site_id": site,
                "base_url": f"https://{site}.example",
                "device_attestation_sha256": str(index + 1) * 64,
            }
            for index, site in enumerate(SITES)
        ],
        "job_id": "physical-job-001",
        "contract_sha256": CONTRACT,
        "expected_rounds": 5,
        "requested_evidence_level": "L3-candidate",
    }
    assert PhysicalFieldAcceptancePlan.model_validate(l3).requested_evidence_level == "L3-candidate"

    l3["sites"][1]["device_attestation_sha256"] = "1" * 64
    with pytest.raises(ValidationError, match="attestations"):
        PhysicalFieldAcceptancePlan.model_validate(l3)


def test_field_plan_rejects_credentials_and_url_userinfo() -> None:
    unsafe = plan().model_dump()
    unsafe["coordinator_base_url"] = "https://operator:secret@coordinator.example"
    unsafe["operator_token"] = "must-not-be-here"

    with pytest.raises(ValidationError):
        PhysicalFieldAcceptancePlan.model_validate(unsafe)
