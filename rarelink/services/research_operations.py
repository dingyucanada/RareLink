"""Multi-study operations, model governance, and evidence lifecycle rules."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from sqlmodel import Session, select

from rarelink.domain import (
    EvidencePackageStatus,
    ModelVersionStatus,
    StudySiteStatus,
    ValidationTier,
    utc_now,
)
from rarelink.models import (
    EvidencePackageRecord,
    ModelVersion,
    Study,
    StudySiteMembership,
)


class ResearchOperationsError(RuntimeError):
    status_code = 409


class RegistryNotFound(ResearchOperationsError):
    status_code = 404


class RegistryGateBlocked(ResearchOperationsError):
    status_code = 422


SITE_TRANSITIONS: dict[StudySiteStatus, frozenset[StudySiteStatus]] = {
    StudySiteStatus.INVITED: frozenset({StudySiteStatus.ACTIVE, StudySiteStatus.WITHDRAWN}),
    StudySiteStatus.ACTIVE: frozenset({StudySiteStatus.PAUSED, StudySiteStatus.WITHDRAWN}),
    StudySiteStatus.PAUSED: frozenset({StudySiteStatus.ACTIVE, StudySiteStatus.WITHDRAWN}),
    StudySiteStatus.WITHDRAWN: frozenset(),
}

MODEL_TRANSITIONS: dict[ModelVersionStatus, frozenset[ModelVersionStatus]] = {
    ModelVersionStatus.CANDIDATE: frozenset({ModelVersionStatus.STATISTICAL_REVIEW}),
    ModelVersionStatus.STATISTICAL_REVIEW: frozenset({ModelVersionStatus.SECURITY_REVIEW}),
    ModelVersionStatus.SECURITY_REVIEW: frozenset(
        {ModelVersionStatus.APPROVED, ModelVersionStatus.REVOKED}
    ),
    ModelVersionStatus.APPROVED: frozenset(
        {ModelVersionStatus.RELEASED, ModelVersionStatus.REVOKED}
    ),
    ModelVersionStatus.RELEASED: frozenset({ModelVersionStatus.REVOKED}),
    ModelVersionStatus.REVOKED: frozenset(),
}

EVIDENCE_TRANSITIONS: dict[EvidencePackageStatus, frozenset[EvidencePackageStatus]] = {
    EvidencePackageStatus.REGISTERED: frozenset(
        {EvidencePackageStatus.VERIFIED, EvidencePackageStatus.REVOKED}
    ),
    EvidencePackageStatus.VERIFIED: frozenset(
        {EvidencePackageStatus.RELEASED, EvidencePackageStatus.REVOKED}
    ),
    EvidencePackageStatus.RELEASED: frozenset({EvidencePackageStatus.REVOKED}),
    EvidencePackageStatus.REVOKED: frozenset(),
}

RELEASE_TIERS = frozenset({ValidationTier.L3_PHYSICAL, ValidationTier.L4_HOSPITAL})


def reason_sha256(reason: str) -> str:
    return hashlib.sha256(reason.strip().encode("utf-8")).hexdigest()


def site_membership_view(item: StudySiteMembership) -> dict[str, Any]:
    return {
        "id": item.id,
        "study_id": item.study_id,
        "site_id": item.site_id,
        "display_name": item.display_name,
        "organization": item.organization,
        "status": item.status,
        "data_use_approved": item.data_use_approved,
        "certificate_bound": item.certificate_bound,
        "dataset_fingerprint": item.dataset_fingerprint,
        "invited_by": item.invited_by,
        "activated_by": item.activated_by,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "activated_at": item.activated_at,
        "withdrawn_at": item.withdrawn_at,
        "contains_patient_data": False,
        "local_path_exported": False,
    }


def evidence_package_view(item: EvidencePackageRecord) -> dict[str, Any]:
    return {
        "id": item.id,
        "study_id": item.study_id,
        "package_sha256": item.package_sha256,
        "manifest_sha256": item.manifest_sha256,
        "model_sha256": item.model_sha256,
        "signing_key_fingerprint_sha256": item.signing_key_fingerprint_sha256,
        "signature_present": bool(item.signature),
        "validation_tier": item.validation_tier,
        "status": item.status,
        "site_count": item.site_count,
        "required_quorum": item.required_quorum,
        "gates": {
            "quorum": item.site_count == item.required_quorum,
            "privacy": item.privacy_gate_passed,
            "security": item.security_gate_passed,
            "dual_approval": item.dual_approval_distinct,
            "no_sensitive_data": not item.contains_sensitive_data,
        },
        "verifier_version": item.verifier_version,
        "registered_by": item.registered_by,
        "verified_by": item.verified_by,
        "released_by": item.released_by,
        "revoked_by": item.revoked_by,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "verified_at": item.verified_at,
        "released_at": item.released_at,
        "revoked_at": item.revoked_at,
        "contains_patient_data": False,
        "private_key_exported": False,
        "signature_exported": False,
    }


def model_version_view(item: ModelVersion) -> dict[str, Any]:
    return {
        "id": item.id,
        "study_id": item.study_id,
        "name": item.name,
        "semantic_version": item.semantic_version,
        "model_family": item.model_family,
        "artifact_sha256": item.artifact_sha256,
        "source_job_id": item.source_job_id,
        "evidence_package_id": item.evidence_package_id,
        "validation_tier": item.validation_tier,
        "status": item.status,
        "metrics": json.loads(item.metrics_json or "{}"),
        "signature_present": bool(item.signature),
        "signing_key_fingerprint_sha256": item.signing_key_fingerprint_sha256,
        "created_by": item.created_by,
        "approved_by": item.approved_by,
        "released_by": item.released_by,
        "revoked_by": item.revoked_by,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "approved_at": item.approved_at,
        "released_at": item.released_at,
        "revoked_at": item.revoked_at,
        "model_binary_exported": False,
        "contains_patient_data": False,
    }


def transition_site_membership(
    item: StudySiteMembership,
    *,
    target: StudySiteStatus,
    actor: str,
    reason: str,
) -> StudySiteMembership:
    if target not in SITE_TRANSITIONS[item.status]:
        raise ResearchOperationsError(
            f"Study site cannot transition from {item.status} to {target}"
        )
    if target == StudySiteStatus.ACTIVE and not (
        item.data_use_approved and item.certificate_bound and item.dataset_fingerprint
    ):
        raise RegistryGateBlocked(
            "Site activation requires data-use approval, certificate binding, "
            "and a dataset fingerprint"
        )
    now = utc_now()
    item.status = target
    item.updated_at = now
    item.reason_sha256 = reason_sha256(reason)
    if target == StudySiteStatus.ACTIVE:
        item.activated_by = actor
        item.activated_at = now
        item.withdrawn_at = None
    elif target == StudySiteStatus.WITHDRAWN:
        item.withdrawn_at = now
    return item


def _require_evidence_release_gates(item: EvidencePackageRecord) -> None:
    if item.validation_tier not in RELEASE_TIERS:
        raise RegistryGateBlocked(
            "A strict research evidence package requires L3 physical or L4 hospital evidence"
        )
    if item.site_count != item.required_quorum:
        raise RegistryGateBlocked("Evidence package does not prove the required quorum")
    if not (item.privacy_gate_passed and item.security_gate_passed and item.dual_approval_distinct):
        raise RegistryGateBlocked("Evidence package governance gates are incomplete")
    if item.contains_sensitive_data:
        raise RegistryGateBlocked("Evidence package contains forbidden sensitive data")
    if not item.signature or not item.signing_key_fingerprint_sha256:
        raise RegistryGateBlocked("Evidence package signature proof is incomplete")


def transition_evidence_package(
    session: Session,
    item: EvidencePackageRecord,
    *,
    target: EvidencePackageStatus,
    actor: str,
    reason: str,
) -> EvidencePackageRecord:
    if target not in EVIDENCE_TRANSITIONS[item.status]:
        raise ResearchOperationsError(
            f"Evidence package cannot transition from {item.status} to {target}"
        )
    now = utc_now()
    if target == EvidencePackageStatus.VERIFIED:
        _require_evidence_release_gates(item)
        if actor == item.registered_by:
            raise RegistryGateBlocked(
                "Evidence package registrant and verifier must be distinct subjects"
            )
        item.verified_by = actor
        item.verified_at = now
    elif target == EvidencePackageStatus.RELEASED:
        _require_evidence_release_gates(item)
        if not item.verified_by or actor == item.verified_by:
            raise RegistryGateBlocked(
                "Evidence verifier and release approver must be distinct subjects"
            )
        item.released_by = actor
        item.released_at = now
    elif target == EvidencePackageStatus.REVOKED:
        item.revoked_by = actor
        item.revoked_at = now
        linked_models = session.exec(
            select(ModelVersion).where(ModelVersion.evidence_package_id == item.id)
        ).all()
        for model in linked_models:
            if model.status != ModelVersionStatus.REVOKED:
                model.status = ModelVersionStatus.REVOKED
                model.revoked_by = actor
                model.revoked_at = now
                model.updated_at = now
                model.reason_sha256 = reason_sha256(reason)
                session.add(model)
    item.status = target
    item.updated_at = now
    item.reason_sha256 = reason_sha256(reason)
    return item


def transition_model_version(
    session: Session,
    item: ModelVersion,
    *,
    target: ModelVersionStatus,
    actor: str,
    evidence_package_id: str | None,
    reason: str,
) -> ModelVersion:
    if target not in MODEL_TRANSITIONS[item.status]:
        raise ResearchOperationsError(
            f"Model version cannot transition from {item.status} to {target}"
        )
    evidence = None
    if evidence_package_id:
        evidence = session.get(EvidencePackageRecord, evidence_package_id)
        if not evidence or evidence.study_id != item.study_id:
            raise RegistryGateBlocked("Evidence package must exist and belong to the same study")
    elif item.evidence_package_id:
        evidence = session.get(EvidencePackageRecord, item.evidence_package_id)

    now = utc_now()
    if target == ModelVersionStatus.SECURITY_REVIEW:
        metrics = json.loads(item.metrics_json or "{}")
        if not metrics:
            raise RegistryGateBlocked("Statistical metrics are required before security review")
    elif target == ModelVersionStatus.APPROVED:
        if not evidence or evidence.status not in {
            EvidencePackageStatus.VERIFIED,
            EvidencePackageStatus.RELEASED,
        }:
            raise RegistryGateBlocked("Model approval requires a verified evidence package")
        if evidence.model_sha256 != item.artifact_sha256:
            raise RegistryGateBlocked(
                "Evidence package model digest does not match the registered artifact"
            )
        if evidence.validation_tier != item.validation_tier:
            raise RegistryGateBlocked("Model and evidence validation tiers do not match")
        if actor == item.created_by:
            raise RegistryGateBlocked(
                "Model creator and approval reviewer must be distinct subjects"
            )
        item.evidence_package_id = evidence.id
        item.approved_by = actor
        item.approved_at = now
    elif target == ModelVersionStatus.RELEASED:
        if not evidence or evidence.status != EvidencePackageStatus.RELEASED:
            raise RegistryGateBlocked("Model release requires a released evidence package")
        if item.validation_tier not in RELEASE_TIERS:
            raise RegistryGateBlocked("Only L3 physical or L4 hospital models may be released")
        if not item.signature or not item.signing_key_fingerprint_sha256:
            raise RegistryGateBlocked(
                "Model release requires a signature and trusted-key fingerprint"
            )
        if actor == item.approved_by:
            raise RegistryGateBlocked(
                "Model approval reviewer and release approver must be distinct subjects"
            )
        item.released_by = actor
        item.released_at = now
    elif target == ModelVersionStatus.REVOKED:
        item.revoked_by = actor
        item.revoked_at = now

    item.status = target
    item.updated_at = now
    item.reason_sha256 = reason_sha256(reason)
    return item


def operations_summary(
    session: Session,
    *,
    organization_id: str | None = None,
) -> dict[str, Any]:
    studies_statement = select(Study)
    if organization_id:
        studies_statement = studies_statement.where(Study.organization_id == organization_id)
    studies = session.exec(studies_statement).all()
    study_ids = {item.id for item in studies}
    memberships = [
        item
        for item in session.exec(select(StudySiteMembership)).all()
        if item.study_id in study_ids
    ]
    models = [
        item for item in session.exec(select(ModelVersion)).all() if item.study_id in study_ids
    ]
    evidence = [
        item
        for item in session.exec(select(EvidencePackageRecord)).all()
        if item.study_id in study_ids
    ]
    study_statuses = Counter(str(item.status) for item in studies)
    site_statuses = Counter(str(item.status) for item in memberships)
    model_statuses = Counter(str(item.status) for item in models)
    evidence_statuses = Counter(str(item.status) for item in evidence)
    alerts = {
        "sites_paused_or_withdrawn": sum(
            site_statuses.get(status, 0)
            for status in (StudySiteStatus.PAUSED, StudySiteStatus.WITHDRAWN)
        ),
        "models_waiting_for_review": sum(
            model_statuses.get(status, 0)
            for status in (
                ModelVersionStatus.CANDIDATE,
                ModelVersionStatus.STATISTICAL_REVIEW,
                ModelVersionStatus.SECURITY_REVIEW,
            )
        ),
        "evidence_waiting_for_verification": evidence_statuses.get(
            EvidencePackageStatus.REGISTERED,
            0,
        ),
    }
    return {
        "schema_version": "rarelink-research-operations-summary-v1",
        "organization_id": organization_id,
        "studies": {"total": len(studies), "by_status": dict(study_statuses)},
        "sites": {"total": len(memberships), "by_status": dict(site_statuses)},
        "models": {"total": len(models), "by_status": dict(model_statuses)},
        "evidence_packages": {
            "total": len(evidence),
            "by_status": dict(evidence_statuses),
        },
        "alerts": alerts,
        "contains_patient_data": False,
        "contains_secret": False,
        "local_paths_exported": False,
    }
