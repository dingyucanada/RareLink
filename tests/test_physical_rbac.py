import json
from dataclasses import asdict, fields

import pytest

from rarelink.security.physical_rbac import (
    ROLE_PERMISSIONS,
    PhysicalApprovalConflict,
    PhysicalPermission,
    PhysicalPermissionDenied,
    PhysicalPrincipal,
    PhysicalRole,
    PhysicalSiteScopeDenied,
    ensure_distinct_approvers,
    permissions_for,
    require_permission,
    require_site_scope,
)


def principal(
    subject_id: str,
    *roles: PhysicalRole,
    site_ids: frozenset[str] = frozenset(),
) -> PhysicalPrincipal:
    return PhysicalPrincipal(
        subject_id=subject_id,
        roles=frozenset(roles),
        organization="hospital-research",
        site_ids=site_ids,
    )


EXPECTED_MATRIX = {
    PhysicalRole.RESEARCH_LEAD: {
        PhysicalPermission.CONTROL_STATE_READ,
        PhysicalPermission.CONTRACT_CREATE,
        PhysicalPermission.CONTRACT_APPROVE,
        PhysicalPermission.JOB_SUBMIT,
        PhysicalPermission.JOB_SYNC,
        PhysicalPermission.JOB_ABORT,
        PhysicalPermission.JOB_RETRY_RESUME,
        PhysicalPermission.MODEL_VERIFY,
        PhysicalPermission.AUDIT_READ,
    },
    PhysicalRole.SITE_ADMIN: {
        PhysicalPermission.CONTROL_STATE_READ,
        PhysicalPermission.SITE_REGISTER,
        PhysicalPermission.JOB_SYNC,
        PhysicalPermission.JOB_ABORT,
        PhysicalPermission.JOB_RETRY_RESUME,
        PhysicalPermission.AUDIT_READ,
    },
    PhysicalRole.DATA_STEWARD: {
        PhysicalPermission.CONTROL_STATE_READ,
        PhysicalPermission.CONTRACT_APPROVE,
        PhysicalPermission.AUDIT_READ,
    },
    PhysicalRole.REVIEWER: {
        PhysicalPermission.CONTROL_STATE_READ,
        PhysicalPermission.CONTRACT_APPROVE,
        PhysicalPermission.MODEL_VERIFY,
        PhysicalPermission.AUDIT_READ,
    },
    PhysicalRole.SECURITY_ADMIN: {
        PhysicalPermission.CONTROL_STATE_READ,
        PhysicalPermission.SITE_REGISTER,
        PhysicalPermission.CONTRACT_APPROVE,
        PhysicalPermission.JOB_SYNC,
        PhysicalPermission.JOB_ABORT,
        PhysicalPermission.AUDIT_READ,
    },
}


@pytest.mark.parametrize("role", list(PhysicalRole))
def test_each_role_has_only_the_reviewed_permission_set(role: PhysicalRole) -> None:
    actor = principal(f"subject-{role.value}", role)
    assert permissions_for(actor) == EXPECTED_MATRIX[role]

    for permission in PhysicalPermission:
        if permission in EXPECTED_MATRIX[role]:
            require_permission(actor, permission)
        else:
            with pytest.raises(PhysicalPermissionDenied) as captured:
                require_permission(actor, permission)
            assert captured.value.status_code == 403
            assert captured.value.error_code == "PHYSICAL_PERMISSION_DENIED"


def test_multi_role_principal_gets_union_without_implicit_permissions() -> None:
    actor = principal(
        "multi-role-subject",
        PhysicalRole.SITE_ADMIN,
        PhysicalRole.REVIEWER,
    )
    assert permissions_for(actor) == (
        EXPECTED_MATRIX[PhysicalRole.SITE_ADMIN]
        | EXPECTED_MATRIX[PhysicalRole.REVIEWER]
    )
    require_permission(actor, PhysicalPermission.SITE_REGISTER)
    require_permission(actor, PhysicalPermission.MODEL_VERIFY)
    with pytest.raises(PhysicalPermissionDenied):
        require_permission(actor, PhysicalPermission.JOB_SUBMIT)


def test_empty_roles_and_unknown_action_fail_closed() -> None:
    actor = principal("no-role-subject")
    assert permissions_for(actor) == frozenset()
    for permission in PhysicalPermission:
        with pytest.raises(PhysicalPermissionDenied):
            require_permission(actor, permission)
    with pytest.raises(PhysicalPermissionDenied, match="not permitted"):
        require_permission(actor, "physical.job.submit")  # type: ignore[arg-type]
    with pytest.raises(PhysicalPermissionDenied, match="verified"):
        require_permission(object(), PhysicalPermission.AUDIT_READ)  # type: ignore[arg-type]


def test_principal_rejects_untrusted_role_strings_instead_of_coercing_them() -> None:
    with pytest.raises(ValueError, match="unrecognized"):
        PhysicalPrincipal(
            subject_id="untrusted-role",
            roles=frozenset({"research_lead"}),  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="frozenset"):
        PhysicalPrincipal(
            subject_id="mutable-role-list",
            roles=[PhysicalRole.RESEARCH_LEAD],  # type: ignore[arg-type]
        )


def test_principal_contains_no_token_or_raw_claim_storage_fields() -> None:
    actor = principal(
        "oidc-subject-123",
        PhysicalRole.RESEARCH_LEAD,
        site_ids=frozenset({"hospital-a"}),
    )
    names = {item.name for item in fields(PhysicalPrincipal)}
    assert names == {"subject_id", "roles", "organization", "site_ids"}
    serialized = json.dumps(actor.safe_identity())
    assert "access_token" not in asdict(actor)
    assert "refresh_token" not in asdict(actor)
    assert "raw_claims" not in asdict(actor)
    assert "oidc-subject-123" in serialized
    assert actor.safe_identity()["access_token_exported"] is False


def test_distinct_authorized_proposer_and_second_approver_are_accepted() -> None:
    proposer = principal("research-lead-1", PhysicalRole.RESEARCH_LEAD)
    approver = principal("reviewer-1", PhysicalRole.REVIEWER)
    ensure_distinct_approvers(proposer, approver)


@pytest.mark.parametrize(
    "approver_role",
    [
        PhysicalRole.RESEARCH_LEAD,
        PhysicalRole.DATA_STEWARD,
        PhysicalRole.REVIEWER,
        PhysicalRole.SECURITY_ADMIN,
    ],
)
def test_all_explicit_approval_roles_can_act_as_distinct_second_approver(
    approver_role: PhysicalRole,
) -> None:
    ensure_distinct_approvers(
        principal("proposer", PhysicalRole.RESEARCH_LEAD),
        principal(f"approver-{approver_role.value}", approver_role),
    )


def test_multi_role_same_subject_cannot_self_approve() -> None:
    proposer = principal(
        "same-issuer-subject",
        PhysicalRole.RESEARCH_LEAD,
        PhysicalRole.REVIEWER,
    )
    same_subject_from_another_session = principal(
        "same-issuer-subject",
        PhysicalRole.SECURITY_ADMIN,
    )
    with pytest.raises(PhysicalApprovalConflict) as captured:
        ensure_distinct_approvers(proposer, same_subject_from_another_session)
    assert captured.value.status_code == 409
    assert captured.value.error_code == "PHYSICAL_APPROVER_NOT_DISTINCT"
    assert captured.value.public_detail()["status_code"] == 409


def test_separation_of_duties_checks_both_action_permissions() -> None:
    with pytest.raises(PhysicalPermissionDenied, match="contract.create"):
        ensure_distinct_approvers(
            principal("site-admin-proposer", PhysicalRole.SITE_ADMIN),
            principal("reviewer", PhysicalRole.REVIEWER),
        )
    with pytest.raises(PhysicalPermissionDenied, match="contract.approve"):
        ensure_distinct_approvers(
            principal("research-lead", PhysicalRole.RESEARCH_LEAD),
            principal("site-admin-approver", PhysicalRole.SITE_ADMIN),
        )


def test_permission_matrix_is_read_only() -> None:
    with pytest.raises(TypeError):
        ROLE_PERMISSIONS[PhysicalRole.SITE_ADMIN] = frozenset(  # type: ignore[index]
            {PhysicalPermission.JOB_SUBMIT}
        )


def test_site_scope_requires_every_target_site_and_fails_closed() -> None:
    actor = principal(
        "scoped-subject",
        PhysicalRole.RESEARCH_LEAD,
        site_ids=frozenset({"hospital-a", "hospital-b", "hospital-c"}),
    )
    require_site_scope(actor, frozenset({"hospital-a"}))
    require_site_scope(actor, frozenset({"hospital-a", "hospital-c"}))

    with pytest.raises(PhysicalSiteScopeDenied) as missing:
        require_site_scope(actor, frozenset({"hospital-a", "hospital-d"}))
    assert missing.value.status_code == 403
    assert missing.value.error_code == "PHYSICAL_SITE_SCOPE_DENIED"
    with pytest.raises(PhysicalSiteScopeDenied):
        require_site_scope(actor, frozenset())
    with pytest.raises(PhysicalSiteScopeDenied):
        require_site_scope(object(), frozenset({"hospital-a"}))  # type: ignore[arg-type]
