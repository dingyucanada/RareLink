"""Tamper-evident, allow-listed audit events for the physical control plane."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, select

from rarelink.domain import utc_now
from rarelink.models import PhysicalControlEvent, new_id

GENESIS_HASH = "0" * 64
CHAIN_APPEND_LOCK_ID = int.from_bytes(
    hashlib.sha256(b"rarelink.physical-audit-chain.v1").digest()[:8],
    byteorder="big",
    signed=True,
)
ALLOWED_PAYLOAD_KEYS = {
    "site.register": {"organization", "expected"},
    "site.heartbeat-accepted": {
        "heartbeat_id",
        "status",
        "dataset_fingerprint",
        "receipt_sha256",
        "current_job_id",
        "current_round",
    },
    "job.dataset-version-invalidated": {
        "error_code",
        "site_id",
        "new_dataset_fingerprint",
        "expected_dataset_fingerprint",
    },
    "job.contract-created": {
        "strategy",
        "bundle_sha256",
        "contract_sha256",
        "expected_sites",
        "dataset_fingerprints",
        "total_rounds",
        "local_epochs",
        "quorum_required",
    },
    "job.contract-second-approved": {
        "approval_id",
        "contract_sha256",
        "attestation",
        "approval_count",
        "expires_at",
    },
    "job.submitted": {
        "external_job_id",
        "strategy",
        "attempt",
        "bundle_sha256",
        "contract_sha256",
        "approval_count",
    },
    "job.status-synchronized": {
        "status",
        "external_job_id",
        "current_round",
        "received_updates",
        "error_code",
    },
    "job.aborted": {"external_job_id", "status", "attempt"},
    "job.retried": {"external_job_id", "status", "attempt"},
    "job.resumed": {"external_job_id", "status", "attempt"},
    "job.global-model-verified": {
        "model_file_name",
        "global_model_sha256",
        "verified",
    },
}
FORBIDDEN_PAYLOAD_KEYS = {
    "admin_kit",
    "api_key",
    "case_id",
    "dataset_manifest",
    "job_directory",
    "label",
    "model_path",
    "password",
    "patient_id",
    "patient_name",
    "private_key",
    "secret",
    "submit_token",
}


class PhysicalAuditError(ValueError):
    pass


def _acquire_chain_append_lock(session: Session) -> None:
    """Serialize chain-head reads across PostgreSQL workers for this transaction."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": CHAIN_APPEND_LOCK_ID},
        )


def _timestamp(value: datetime) -> str:
    normalized = value if value.tzinfo else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _reject_sensitive_payload(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).strip().lower() in FORBIDDEN_PAYLOAD_KEYS:
                raise PhysicalAuditError(
                    "Sensitive or patient-level fields are forbidden in physical audit events"
                )
            _reject_sensitive_payload(child)
    elif isinstance(value, list):
        for child in value:
            _reject_sensitive_payload(child)


def _validate_payload(action: str, payload: dict[str, Any]) -> None:
    _reject_sensitive_payload(payload)
    allowed = ALLOWED_PAYLOAD_KEYS.get(action)
    if allowed is None:
        raise PhysicalAuditError(f"Unsupported physical audit action: {action}")
    unknown = set(payload) - allowed
    if unknown:
        raise PhysicalAuditError(
            "Physical audit payload contains fields outside the action allow-list"
        )


def _canonical_event(
    *,
    event_id: str,
    action: str,
    actor: str,
    resource_type: str,
    resource_id: str,
    outcome: str,
    payload: dict[str, Any],
    previous_hash: str,
    algorithm: str,
    key_id: str | None,
    created_at: datetime,
) -> bytes:
    return json.dumps(
        {
            "event_id": event_id,
            "action": action,
            "actor": actor,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "outcome": outcome,
            "payload": payload,
            "previous_hash": previous_hash,
            "algorithm": algorithm,
            "key_id": key_id,
            "created_at": _timestamp(created_at),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _event_hash(encoded: bytes, hmac_key: str) -> str:
    if hmac_key:
        return hmac.new(hmac_key.encode("utf-8"), encoded, hashlib.sha256).hexdigest()
    return hashlib.sha256(encoded).hexdigest()


def append_physical_event(
    session: Session,
    *,
    action: str,
    actor: str,
    resource_type: str,
    resource_id: str,
    outcome: str,
    payload: dict[str, Any] | None = None,
    hmac_key: str = "",
) -> PhysicalControlEvent:
    safe_payload = payload or {}
    _validate_payload(action, safe_payload)
    _acquire_chain_append_lock(session)
    previous = session.exec(
        select(PhysicalControlEvent).order_by(PhysicalControlEvent.id.desc())
    ).first()
    previous_hash = previous.event_hash if previous else GENESIS_HASH
    event_id = new_id("physical-event")
    created_at = utc_now()
    algorithm = "HMAC-SHA256" if hmac_key else "SHA256"
    key_id = (
        hashlib.sha256(hmac_key.encode("utf-8")).hexdigest()[:16]
        if hmac_key
        else None
    )
    encoded = _canonical_event(
        event_id=event_id,
        action=action,
        actor=actor,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        payload=safe_payload,
        previous_hash=previous_hash,
        algorithm=algorithm,
        key_id=key_id,
        created_at=created_at,
    )
    event = PhysicalControlEvent(
        event_id=event_id,
        action=action,
        actor=actor,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        payload_json=json.dumps(
            safe_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        previous_hash=previous_hash,
        event_hash=_event_hash(encoded, hmac_key),
        algorithm=algorithm,
        key_id=key_id,
        created_at=created_at,
    )
    session.add(event)
    return event


def verify_physical_event_chain(
    events: list[PhysicalControlEvent],
    *,
    hmac_key: str = "",
) -> bool:
    expected_previous = GENESIS_HASH
    current_key_id = (
        hashlib.sha256(hmac_key.encode("utf-8")).hexdigest()[:16]
        if hmac_key
        else None
    )
    for event in events:
        try:
            payload = json.loads(event.payload_json)
            if not isinstance(payload, dict):
                return False
            _validate_payload(event.action, payload)
        except (json.JSONDecodeError, PhysicalAuditError):
            return False
        if event.previous_hash != expected_previous:
            return False
        if event.algorithm == "SHA256" and event.key_id is None:
            event_key = ""
        elif (
            event.algorithm == "HMAC-SHA256"
            and hmac_key
            and event.key_id == current_key_id
        ):
            event_key = hmac_key
        else:
            return False
        encoded = _canonical_event(
            event_id=event.event_id,
            action=event.action,
            actor=event.actor,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            outcome=event.outcome,
            payload=payload,
            previous_hash=event.previous_hash,
            algorithm=event.algorithm,
            key_id=event.key_id,
            created_at=event.created_at,
        )
        if not hmac.compare_digest(event.event_hash, _event_hash(encoded, event_key)):
            return False
        expected_previous = event.event_hash
    return True
