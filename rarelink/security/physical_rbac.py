"""Fail-closed authorization core for the physical federation control plane.

This module is intentionally not an OIDC implementation. A future OIDC claims
adapter must validate issuer, audience, signature, time bounds, and role claims
before constructing :class:`PhysicalPrincipal`. Access tokens, refresh tokens,
client secrets, and raw claims must never be stored on the principal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class PhysicalRole(StrEnum):
    RESEARCH_LEAD = "research_lead"
    SITE_ADMIN = "site_admin"
    DATA_STEWARD = "data_steward"
    REVIEWER = "reviewer"
    SECURITY_ADMIN = "security_admin"


class PhysicalPermission(StrEnum):
    CONTROL_STATE_READ = "physical.control_state.read"
    SITE_REGISTER = "physical.site.register"
    CONTRACT_CREATE = "physical.contract.create"
    CONTRACT_APPROVE = "physical.contract.approve"
    CONTRACT_REVOKE = "physical.contract.revoke"
    JOB_SUBMIT = "physical.job.submit"
    JOB_SYNC = "physical.job.sync"
    JOB_ABORT = "physical.job.abort"
    JOB_RETRY_RESUME = "physical.job.retry_resume"
    MODEL_VERIFY = "physical.model.verify"
    PRIVACY_BUDGET_MANAGE = "physical.privacy_budget.manage"
    PRIVACY_SPEND_REPORT = "physical.privacy_spend.report"
    AUDIT_READ = "physical.audit.read"


_ROLE_PERMISSIONS_SOURCE: Final[dict[PhysicalRole, frozenset[PhysicalPermission]]] = {
    PhysicalRole.RESEARCH_LEAD: frozenset(
        {
            PhysicalPermission.CONTROL_STATE_READ,
            PhysicalPermission.CONTRACT_CREATE,
            PhysicalPermission.CONTRACT_APPROVE,
            PhysicalPermission.CONTRACT_REVOKE,
            PhysicalPermission.JOB_SUBMIT,
            PhysicalPermission.JOB_SYNC,
            PhysicalPermission.JOB_ABORT,
            PhysicalPermission.JOB_RETRY_RESUME,
            PhysicalPermission.MODEL_VERIFY,
            PhysicalPermission.PRIVACY_BUDGET_MANAGE,
            PhysicalPermission.AUDIT_READ,
        }
    ),
    PhysicalRole.SITE_ADMIN: frozenset(
        {
            PhysicalPermission.CONTROL_STATE_READ,
            PhysicalPermission.SITE_REGISTER,
            PhysicalPermission.JOB_SYNC,
            PhysicalPermission.JOB_ABORT,
            PhysicalPermission.JOB_RETRY_RESUME,
            PhysicalPermission.PRIVACY_SPEND_REPORT,
            PhysicalPermission.AUDIT_READ,
        }
    ),
    PhysicalRole.DATA_STEWARD: frozenset(
        {
            PhysicalPermission.CONTROL_STATE_READ,
            PhysicalPermission.CONTRACT_APPROVE,
            PhysicalPermission.CONTRACT_REVOKE,
            PhysicalPermission.PRIVACY_BUDGET_MANAGE,
            PhysicalPermission.AUDIT_READ,
        }
    ),
    PhysicalRole.REVIEWER: frozenset(
        {
            PhysicalPermission.CONTROL_STATE_READ,
            PhysicalPermission.CONTRACT_APPROVE,
            PhysicalPermission.MODEL_VERIFY,
            PhysicalPermission.PRIVACY_BUDGET_MANAGE,
            PhysicalPermission.AUDIT_READ,
        }
    ),
    PhysicalRole.SECURITY_ADMIN: frozenset(
        {
            PhysicalPermission.CONTROL_STATE_READ,
            PhysicalPermission.SITE_REGISTER,
            PhysicalPermission.CONTRACT_APPROVE,
            PhysicalPermission.CONTRACT_REVOKE,
            PhysicalPermission.JOB_SYNC,
            PhysicalPermission.JOB_ABORT,
            PhysicalPermission.PRIVACY_BUDGET_MANAGE,
            PhysicalPermission.PRIVACY_SPEND_REPORT,
            PhysicalPermission.AUDIT_READ,
        }
    ),
}

# Read-only by construction: callers cannot grant a role additional permissions
# by mutating the exported matrix.
ROLE_PERMISSIONS: Final = MappingProxyType(_ROLE_PERMISSIONS_SOURCE)


class PhysicalAccessControlError(RuntimeError):
    """Safe domain error that an API adapter can translate without parsing text."""

    status_code: int
    error_code: str

    def __init__(self, message: str):
        super().__init__(message)

    def public_detail(self) -> dict[str, str | int]:
        return {
            "code": self.error_code,
            "message": str(self),
            "status_code": self.status_code,
        }


class PhysicalPermissionDenied(PhysicalAccessControlError):
    status_code = 403
    error_code = "PHYSICAL_PERMISSION_DENIED"


class PhysicalSiteScopeDenied(PhysicalAccessControlError):
    status_code = 403
    error_code = "PHYSICAL_SITE_SCOPE_DENIED"


class PhysicalApprovalConflict(PhysicalAccessControlError):
    status_code = 409
    error_code = "PHYSICAL_APPROVER_NOT_DISTINCT"


@dataclass(frozen=True, slots=True)
class PhysicalPrincipal:
    """Minimal verified identity used by the authorization core.

    ``subject_id`` is the stable issuer-scoped subject from a trusted adapter,
    not a display name. ``site_ids`` constrains future resource-level checks; the
    permission matrix in this module grants action types only.
    """

    subject_id: str
    roles: frozenset[PhysicalRole]
    organization: str | None = None
    site_ids: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        subject_id = self.subject_id.strip()
        if not subject_id or len(subject_id) > 255:
            raise ValueError("subject_id must contain between 1 and 255 characters")
        if any(character.isspace() for character in subject_id):
            raise ValueError("subject_id must not contain whitespace")
        if not isinstance(self.roles, frozenset):
            raise TypeError("roles must be a frozenset of PhysicalRole values")
        if any(not isinstance(role, PhysicalRole) for role in self.roles):
            raise ValueError("roles contains an unrecognized physical federation role")
        if not isinstance(self.site_ids, frozenset):
            raise TypeError("site_ids must be a frozenset")
        if any(
            not isinstance(site_id, str) or not site_id.strip() or len(site_id) > 63
            for site_id in self.site_ids
        ):
            raise ValueError("site_ids must contain non-empty identifiers up to 63 characters")
        if self.organization is not None:
            organization = self.organization.strip()
            if not organization or len(organization) > 160:
                raise ValueError("organization must contain between 1 and 160 characters")
            object.__setattr__(self, "organization", organization)
        object.__setattr__(self, "subject_id", subject_id)

    def safe_identity(self) -> dict[str, object]:
        """Return allow-listed audit identity data, never raw OIDC claims or tokens."""
        return {
            "subject_id": self.subject_id,
            "roles": sorted(role.value for role in self.roles),
            "organization": self.organization,
            "site_ids": sorted(self.site_ids),
            "access_token_exported": False,
            "refresh_token_exported": False,
            "raw_claims_exported": False,
        }


def permissions_for(principal: PhysicalPrincipal) -> frozenset[PhysicalPermission]:
    """Return the union of known role grants; an empty/unknown set grants nothing."""
    permissions: set[PhysicalPermission] = set()
    for role in principal.roles:
        permissions.update(ROLE_PERMISSIONS.get(role, frozenset()))
    return frozenset(permissions)


def require_permission(
    principal: PhysicalPrincipal,
    permission: PhysicalPermission,
) -> None:
    """Authorize one action or raise a safe error suitable for HTTP 403 mapping."""
    if not isinstance(principal, PhysicalPrincipal):
        raise PhysicalPermissionDenied("A verified physical federation principal is required")
    if not isinstance(permission, PhysicalPermission):
        raise PhysicalPermissionDenied("The requested physical federation action is not permitted")
    if permission not in permissions_for(principal):
        raise PhysicalPermissionDenied(
            f"Principal is not authorized for action {permission.value}"
        )


def require_site_scope(
    principal: PhysicalPrincipal,
    required_site_ids: frozenset[str],
) -> None:
    """Require every target physical site to be present in verified OIDC scope."""
    if not isinstance(principal, PhysicalPrincipal):
        raise PhysicalSiteScopeDenied(
            "A verified physical federation principal is required"
        )
    if (
        not isinstance(required_site_ids, frozenset)
        or not required_site_ids
        or any(
            not isinstance(site_id, str) or not site_id.strip()
            for site_id in required_site_ids
        )
    ):
        raise PhysicalSiteScopeDenied("Physical federation site scope is invalid")
    if not required_site_ids.issubset(principal.site_ids):
        raise PhysicalSiteScopeDenied(
            "Principal is not authorized for every target physical site"
        )


def ensure_distinct_approvers(
    proposer: PhysicalPrincipal,
    second_approver: PhysicalPrincipal,
) -> None:
    """Enforce two-person control for a proposed physical research contract.

    A multi-role subject remains one person. Possessing both ``research_lead``
    and an approval-capable role never satisfies separation of duties.
    """
    if not isinstance(proposer, PhysicalPrincipal) or not isinstance(
        second_approver, PhysicalPrincipal
    ):
        raise PhysicalPermissionDenied("Two verified physical federation principals are required")
    if proposer.subject_id == second_approver.subject_id:
        raise PhysicalApprovalConflict(
            "Contract proposer and second approver must be distinct subjects"
        )
    require_permission(proposer, PhysicalPermission.CONTRACT_CREATE)
    require_permission(second_approver, PhysicalPermission.CONTRACT_APPROVE)
