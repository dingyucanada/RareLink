import json
from typing import Any

from sqlmodel import Session, select

from rarelink.models import AuditEvent


def append_event(
    session: Session,
    study_id: str,
    event_type: str,
    actor: str,
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        study_id=study_id,
        event_type=event_type,
        actor=actor,
        payload_json=json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
    )
    session.add(event)
    return event


def list_events(session: Session, study_id: str) -> list[AuditEvent]:
    statement = (
        select(AuditEvent).where(AuditEvent.study_id == study_id).order_by(AuditEvent.created_at)
    )
    return list(session.exec(statement).all())
