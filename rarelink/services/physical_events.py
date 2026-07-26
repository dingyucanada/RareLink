"""Durable, de-identified Server-Sent Events for the physical control plane."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from sqlmodel import Session, select

from rarelink.models import PhysicalControlEvent
from rarelink.services.physical_controller import JobValidationError

EVENT_ID_RE = re.compile(r"^physical-event-[a-f0-9]{12}$")


@dataclass(frozen=True)
class SafePhysicalEvent:
    event_id: str
    action: str
    outcome: str
    resource_type: str
    resource_id: str
    created_at: str
    payload_sha256: str

    def public_data(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "action": self.action,
            "outcome": self.outcome,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "created_at": self.created_at,
            "payload_sha256": self.payload_sha256,
            "contains_patient_data": False,
            "contains_secret": False,
            "contains_local_path": False,
        }


def _safe_event(event: PhysicalControlEvent) -> SafePhysicalEvent:
    observed_at = event.created_at
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    return SafePhysicalEvent(
        event_id=event.event_id,
        action=event.action,
        outcome=event.outcome,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        created_at=observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        payload_sha256=hashlib.sha256(event.payload_json.encode("utf-8")).hexdigest(),
    )


def fetch_safe_job_events(
    session: Session,
    job_id: str,
    *,
    last_event_id: str | None,
    limit: int = 100,
) -> list[SafePhysicalEvent]:
    if not 1 <= limit <= 500:
        raise JobValidationError("SSE event limit must be between 1 and 500")
    cursor_id: int | None = None
    if last_event_id:
        if not EVENT_ID_RE.fullmatch(last_event_id):
            raise JobValidationError("Last-Event-ID is invalid")
        cursor = session.exec(
            select(PhysicalControlEvent).where(
                PhysicalControlEvent.event_id == last_event_id,
                PhysicalControlEvent.resource_type == "physical-job",
                PhysicalControlEvent.resource_id == job_id,
            )
        ).first()
        if cursor is None or cursor.id is None:
            raise JobValidationError(
                "Last-Event-ID is not available for the requested physical job"
            )
        cursor_id = cursor.id
    statement = (
        select(PhysicalControlEvent)
        .where(
            PhysicalControlEvent.resource_type == "physical-job",
            PhysicalControlEvent.resource_id == job_id,
        )
        .order_by(PhysicalControlEvent.id)
        .limit(limit)
    )
    if cursor_id is not None:
        statement = statement.where(PhysicalControlEvent.id > cursor_id)
    return [_safe_event(event) for event in session.exec(statement).all()]


def encode_sse(event: SafePhysicalEvent) -> str:
    data = json.dumps(
        event.public_data(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return f"id: {event.event_id}\nevent: physical-control-event\ndata: {data}\n\n"
