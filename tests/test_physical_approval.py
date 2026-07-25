import json
from types import SimpleNamespace

import pytest

from rarelink.security.physical_rbac import (
    PhysicalApprovalConflict,
    PhysicalPermissionDenied,
    PhysicalPrincipal,
    PhysicalRole,
)
from rarelink.services.physical_approval import (
    PhysicalContractChangedError,
    PhysicalContractValidationError,
    canonical_contract_payload,
    canonical_contract_sha256,
    ensure_job_second_approval,
    principal_from_job_proposer,
    verify_contract_unchanged,
)

SITE_HASHES = {
    "hospital-a": "a" * 64,
    "hospital-b": "b" * 64,
    "hospital-c": "c" * 64,
}


def job(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "study_id": "study-physical-001",
        "strategy": "fedavg",
        "bundle_sha256": "d" * 64,
        "expected_sites_json": json.dumps(
            ["hospital-a", "hospital-b", "hospital-c"]
        ),
        "dataset_fingerprints_json": json.dumps(SITE_HASHES),
        "total_rounds": 5,
        "local_epochs": 1,
        "quorum_required": 3,
        "proposed_by": "issuer-subject-proposer",
        "proposer_roles_json": json.dumps([PhysicalRole.RESEARCH_LEAD.value]),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def approver(
    subject_id: str = "issuer-subject-reviewer",
    role: PhysicalRole = PhysicalRole.REVIEWER,
) -> PhysicalPrincipal:
    return PhysicalPrincipal(subject_id=subject_id, roles=frozenset({role}))


def test_contract_digest_is_canonical_across_json_order_and_whitespace() -> None:
    first = job()
    second = job(
        expected_sites_json='[ "hospital-c", "hospital-a", "hospital-b" ]',
        dataset_fingerprints_json=json.dumps(
            {
                "hospital-c": "c" * 64,
                "hospital-a": "a" * 64,
                "hospital-b": "b" * 64,
            },
            indent=2,
        ),
    )
    assert canonical_contract_sha256(first) == canonical_contract_sha256(second)
    assert len(canonical_contract_sha256(first)) == 64
    assert canonical_contract_payload(first)["expected_sites"] == [
        "hospital-a",
        "hospital-b",
        "hospital-c",
    ]
    assert canonical_contract_sha256(job(study_id=None)) == canonical_contract_sha256(
        job(study_id=None)
    )


@pytest.mark.parametrize(
    ("field_name", "changed_value"),
    [
        ("study_id", "study-physical-002"),
        ("strategy", "fedprox"),
        ("bundle_sha256", "e" * 64),
        (
            "dataset_fingerprints_json",
            json.dumps({**SITE_HASHES, "hospital-c": "f" * 64}),
        ),
        ("total_rounds", 6),
        ("local_epochs", 2),
    ],
)
def test_every_material_contract_change_changes_digest(
    field_name: str,
    changed_value: object,
) -> None:
    original = canonical_contract_sha256(job())
    changed = canonical_contract_sha256(job(**{field_name: changed_value}))
    assert original != changed


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"expected_sites_json": "not-json"}, "not valid JSON"),
        ({"expected_sites_json": "{}"}, "exactly three"),
        (
            {
                "expected_sites_json": json.dumps(
                    ["hospital-a", "hospital-a", "hospital-c"]
                )
            },
            "must be unique",
        ),
        (
            {"expected_sites_json": json.dumps(["hospital-a", "Patient 1", "hospital-c"])},
            "invalid expected site",
        ),
        ({"dataset_fingerprints_json": "[]"}, "JSON object"),
        (
            {
                "dataset_fingerprints_json": json.dumps(
                    {"hospital-a": "a" * 64, "hospital-b": "b" * 64}
                )
            },
            "match the three",
        ),
        (
            {
                "dataset_fingerprints_json": json.dumps(
                    {**SITE_HASHES, "hospital-c": "not-a-sha"}
                )
            },
            "lower-case SHA-256",
        ),
        ({"bundle_sha256": "not-a-sha"}, "bundle_sha256"),
        ({"total_rounds": 0}, "positive integer"),
        ({"total_rounds": True}, "positive integer"),
        ({"quorum_required": 2}, "all three"),
        ({"strategy": "local"}, "fedavg or fedprox"),
    ],
)
def test_invalid_contracts_fail_closed_without_echoing_values(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(PhysicalContractValidationError, match=message) as captured:
        canonical_contract_sha256(job(**overrides))
    assert captured.value.status_code == 400
    rendered = str(captured.value)
    assert "Patient 1" not in rendered
    assert "not-a-sha" not in rendered


def test_missing_future_model_fields_fail_safely() -> None:
    incomplete = SimpleNamespace(study_id="study-only")
    with pytest.raises(PhysicalContractValidationError, match="strategy"):
        canonical_contract_sha256(incomplete)
    with pytest.raises(PhysicalContractValidationError, match="proposed_by"):
        principal_from_job_proposer(incomplete)


def test_verify_contract_unchanged_uses_409_conflict_for_mutation() -> None:
    proposed = job()
    digest = canonical_contract_sha256(proposed)
    assert verify_contract_unchanged(proposed, digest) == digest

    changed = job(total_rounds=10)
    with pytest.raises(PhysicalContractChangedError) as captured:
        verify_contract_unchanged(changed, digest)
    assert captured.value.status_code == 409
    assert captured.value.error_code == "PHYSICAL_CONTRACT_CHANGED"
    assert captured.value.public_detail()["status_code"] == 409

    with pytest.raises(PhysicalContractValidationError, match="Expected"):
        verify_contract_unchanged(proposed, "invalid")


def test_proposer_principal_is_rebuilt_from_minimum_fields_only() -> None:
    record = job(
        access_token="must-never-be-read",
        patient_name="must-never-be-read",
        admin_kit_path="/must/never/be/read",
    )
    principal = principal_from_job_proposer(record)
    assert principal.subject_id == "issuer-subject-proposer"
    assert principal.roles == frozenset({PhysicalRole.RESEARCH_LEAD})
    safe = json.dumps(principal.safe_identity())
    assert "must-never-be-read" not in safe
    assert principal.organization is None
    assert principal.site_ids == frozenset()


@pytest.mark.parametrize(
    "roles_json",
    [
        None,
        "{}",
        "[]",
        json.dumps(["unknown_role"]),
        json.dumps([PhysicalRole.RESEARCH_LEAD.value, PhysicalRole.RESEARCH_LEAD.value]),
    ],
)
def test_proposer_role_reconstruction_fails_closed(roles_json: object) -> None:
    with pytest.raises(PhysicalContractValidationError):
        principal_from_job_proposer(job(proposer_roles_json=roles_json))


def test_second_approval_locks_digest_and_enforces_distinct_subjects() -> None:
    record = job()
    digest = canonical_contract_sha256(record)
    assert (
        ensure_job_second_approval(
            record,
            approver(),
            expected_contract_sha256=digest,
        )
        == digest
    )

    same_subject = approver(
        subject_id="issuer-subject-proposer",
        role=PhysicalRole.SECURITY_ADMIN,
    )
    with pytest.raises(PhysicalApprovalConflict) as captured:
        ensure_job_second_approval(record, same_subject)
    assert captured.value.status_code == 409


def test_second_approval_checks_both_roles_and_frozen_contract() -> None:
    non_proposer = job(
        proposer_roles_json=json.dumps([PhysicalRole.SITE_ADMIN.value])
    )
    with pytest.raises(PhysicalPermissionDenied, match="contract.create"):
        ensure_job_second_approval(non_proposer, approver())

    with pytest.raises(PhysicalPermissionDenied, match="contract.approve"):
        ensure_job_second_approval(
            job(),
            approver(role=PhysicalRole.SITE_ADMIN),
        )

    original_digest = canonical_contract_sha256(job())
    with pytest.raises(PhysicalContractChangedError):
        ensure_job_second_approval(
            job(local_epochs=2),
            approver(),
            expected_contract_sha256=original_digest,
        )
