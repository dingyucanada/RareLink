import json

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from rarelink.models import PhysicalControlEvent
from rarelink.services.physical_audit import (
    PhysicalAuditError,
    append_physical_event,
    verify_physical_event_chain,
)


def test_physical_audit_chain_detects_tampering_and_uses_hmac() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    key = "physical-audit-test-key-000000000000"
    with Session(engine) as session:
        append_physical_event(
            session,
            action="site.register",
            actor="operator-a",
            resource_type="physical-site",
            resource_id="hospital-a",
            outcome="accepted",
            payload={"expected": True},
            hmac_key=key,
        )
        append_physical_event(
            session,
            action="job.contract-created",
            actor="operator-a",
            resource_type="physical-job",
            resource_id="job-001",
            outcome="approval-pending",
            payload={"bundle_sha256": "a" * 64},
            hmac_key=key,
        )
        session.commit()
        events = list(
            session.exec(
                select(PhysicalControlEvent).order_by(PhysicalControlEvent.id)
            ).all()
        )

        assert verify_physical_event_chain(events, hmac_key=key) is True
        assert events[0].algorithm == "HMAC-SHA256"
        assert events[1].previous_hash == events[0].event_hash

        events[0].payload_json = json.dumps({"expected": False})
        assert verify_physical_event_chain(events, hmac_key=key) is False


def test_physical_audit_rejects_sensitive_payload_fields() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session, pytest.raises(
        PhysicalAuditError,
        match="Sensitive",
    ):
        append_physical_event(
            session,
            action="job.submitted",
            actor="operator-a",
            resource_type="physical-job",
            resource_id="job-001",
            outcome="accepted",
            payload={"submit_token": "must-not-be-recorded"},
        )


def test_physical_audit_rejects_fields_outside_action_allow_list() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session, pytest.raises(
        PhysicalAuditError,
        match="allow-list",
    ):
        append_physical_event(
            session,
            action="site.register",
            actor="operator-a",
            resource_type="physical-site",
            resource_id="hospital-a",
            outcome="accepted",
            payload={"organization": "hospital_a", "unexpected": "not-recorded"},
        )


def test_physical_audit_verifies_sha256_history_before_hmac_enablement() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    key = "physical-audit-test-key-000000000000"
    with Session(engine) as session:
        append_physical_event(
            session,
            action="site.register",
            actor="operator-a",
            resource_type="physical-site",
            resource_id="hospital-a",
            outcome="accepted",
        )
        session.flush()
        append_physical_event(
            session,
            action="site.heartbeat-accepted",
            actor="hospital-a",
            resource_type="physical-site",
            resource_id="hospital-a",
            outcome="accepted",
            hmac_key=key,
        )
        session.commit()
        events = list(
            session.exec(
                select(PhysicalControlEvent).order_by(PhysicalControlEvent.id)
            ).all()
        )

    assert verify_physical_event_chain(events, hmac_key=key) is True
