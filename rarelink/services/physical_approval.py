"""Canonical contract locking and two-person approval for physical FL jobs.

The functions accept a job-shaped object instead of importing SQLModel. This
keeps the security core independently testable and permits a repository adapter
to supply either a database model or an immutable projection.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

from rarelink.security.physical_rbac import (
    PhysicalPrincipal,
    PhysicalRole,
    ensure_distinct_approvers,
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SITE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,62}$")
ALLOWED_STRATEGIES = frozenset({"fedavg", "fedprox", "fedavg_dpsgd"})


class PhysicalApprovalServiceError(RuntimeError):
    """Safe service error that an API adapter may expose by code."""

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


class PhysicalContractValidationError(PhysicalApprovalServiceError):
    status_code = 400
    error_code = "PHYSICAL_CONTRACT_INVALID"


class PhysicalContractChangedError(PhysicalApprovalServiceError):
    status_code = 409
    error_code = "PHYSICAL_CONTRACT_CHANGED"


def _required_text(job: object, field_name: str, *, max_length: int = 255) -> str:
    value = getattr(job, field_name, None)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
        raise PhysicalContractValidationError(
            f"Physical contract field {field_name!r} is missing or invalid"
        )
    return value.strip()


def _strict_json(job: object, field_name: str) -> Any:
    raw = getattr(job, field_name, None)
    if not isinstance(raw, str):
        raise PhysicalContractValidationError(
            f"Physical contract field {field_name!r} must be encoded JSON"
        )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PhysicalContractValidationError(
            f"Physical contract field {field_name!r} is not valid JSON"
        ) from exc


def _positive_integer(job: object, *field_names: str) -> int:
    for field_name in field_names:
        value = getattr(job, field_name, None)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    joined = " or ".join(repr(name) for name in field_names)
    raise PhysicalContractValidationError(
        f"Physical contract field {joined} must be a positive integer"
    )


def _expected_sites(job: object) -> tuple[str, str, str]:
    sites = _strict_json(job, "expected_sites_json")
    if not isinstance(sites, list) or len(sites) != 3:
        raise PhysicalContractValidationError(
            "Physical contract requires exactly three expected sites"
        )
    if any(not isinstance(site, str) or not SITE_ID_RE.fullmatch(site) for site in sites):
        raise PhysicalContractValidationError(
            "Physical contract contains an invalid expected site identifier"
        )
    if len(set(sites)) != 3:
        raise PhysicalContractValidationError(
            "Physical contract expected sites must be unique"
        )
    canonical = tuple(sorted(sites))
    return canonical[0], canonical[1], canonical[2]


def _dataset_fingerprints(
    job: object,
    expected_sites: tuple[str, str, str],
) -> dict[str, str]:
    fingerprints = _strict_json(job, "dataset_fingerprints_json")
    if not isinstance(fingerprints, dict):
        raise PhysicalContractValidationError(
            "Physical contract dataset fingerprints must be a JSON object"
        )
    if set(fingerprints) != set(expected_sites):
        raise PhysicalContractValidationError(
            "Dataset fingerprints must match the three expected site identities"
        )
    if any(
        not isinstance(value, str) or not SHA256_RE.fullmatch(value)
        for value in fingerprints.values()
    ):
        raise PhysicalContractValidationError(
            "Every site dataset fingerprint must be a lower-case SHA-256 value"
        )
    return {site: fingerprints[site] for site in expected_sites}


def canonical_contract_payload(job: object) -> dict[str, Any]:
    """Return the strictly validated, order-independent contract projection."""
    raw_study_id = getattr(job, "study_id", None)
    if raw_study_id is None:
        study_id = None
    elif (
        isinstance(raw_study_id, str)
        and raw_study_id.strip()
        and len(raw_study_id.strip()) <= 255
    ):
        study_id = raw_study_id.strip()
    else:
        raise PhysicalContractValidationError(
            "Physical contract field 'study_id' is invalid"
        )
    strategy = _required_text(job, "strategy", max_length=32).lower()
    if strategy not in ALLOWED_STRATEGIES:
        raise PhysicalContractValidationError(
            "Physical contract strategy must be fedavg or fedprox, or fedavg_dpsgd"
        )
    bundle_sha256 = _required_text(job, "bundle_sha256", max_length=64)
    if not SHA256_RE.fullmatch(bundle_sha256):
        raise PhysicalContractValidationError(
            "Physical contract bundle_sha256 must be a lower-case SHA-256 value"
        )
    expected_sites = _expected_sites(job)
    fingerprints = _dataset_fingerprints(job, expected_sites)
    rounds = _positive_integer(job, "rounds", "total_rounds")
    local_epochs = _positive_integer(job, "local_epochs")
    quorum = _positive_integer(job, "quorum", "quorum_required")
    if quorum != 3:
        raise PhysicalContractValidationError(
            "Physical v1 contract quorum must require all three expected sites"
        )
    return {
        "schema_version": "rarelink-physical-contract-v1",
        "study_id": study_id,
        "strategy": strategy,
        "bundle_sha256": bundle_sha256,
        "expected_sites": list(expected_sites),
        "dataset_fingerprints": fingerprints,
        "rounds": rounds,
        "local_epochs": local_epochs,
        "quorum": quorum,
    }


def canonical_contract_sha256(job: object) -> str:
    payload = json.dumps(
        canonical_contract_payload(job),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_contract_unchanged(job: object, expected_sha256: str) -> str:
    """Return the current digest or raise a safe HTTP-409-mappable conflict."""
    if not isinstance(expected_sha256, str) or not SHA256_RE.fullmatch(expected_sha256):
        raise PhysicalContractValidationError(
            "Expected physical contract digest must be a lower-case SHA-256 value"
        )
    actual = canonical_contract_sha256(job)
    if not hmac.compare_digest(actual, expected_sha256):
        raise PhysicalContractChangedError(
            "Physical federation contract changed after proposal and requires new approval"
        )
    return actual


def principal_from_job_proposer(job: object) -> PhysicalPrincipal:
    """Rebuild the minimal proposer identity from an immutable job projection.

    This is not token parsing and does not validate OIDC. The persistence adapter
    must write these fields only from an already authenticated principal.
    """
    proposed_by = _required_text(job, "proposed_by")
    raw_roles = _strict_json(job, "proposer_roles_json")
    if not isinstance(raw_roles, list) or not raw_roles:
        raise PhysicalContractValidationError(
            "Physical contract proposer roles must be a non-empty JSON list"
        )
    if any(not isinstance(role, str) for role in raw_roles):
        raise PhysicalContractValidationError(
            "Physical contract proposer roles contain an invalid value"
        )
    try:
        roles = frozenset(PhysicalRole(role) for role in raw_roles)
    except ValueError as exc:
        raise PhysicalContractValidationError(
            "Physical contract proposer roles contain an unrecognized role"
        ) from exc
    if len(roles) != len(raw_roles):
        raise PhysicalContractValidationError(
            "Physical contract proposer roles must be unique"
        )
    try:
        return PhysicalPrincipal(subject_id=proposed_by, roles=roles)
    except (TypeError, ValueError) as exc:
        raise PhysicalContractValidationError(
            "Physical contract proposer identity is invalid"
        ) from exc


def ensure_job_second_approval(
    job: object,
    second_approver: PhysicalPrincipal,
    *,
    expected_contract_sha256: str | None = None,
) -> str:
    """Validate frozen contract and two-person control, returning its digest."""
    digest = canonical_contract_sha256(job)
    if expected_contract_sha256 is not None:
        digest = verify_contract_unchanged(job, expected_contract_sha256)
    proposer = principal_from_job_proposer(job)
    ensure_distinct_approvers(proposer, second_approver)
    return digest
