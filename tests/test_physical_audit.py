import json
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from rarelink.models import PhysicalControlEvent
from rarelink.services.physical_audit import (
    CHAIN_APPEND_LOCK_ID,
    PhysicalAuditError,
    _acquire_chain_append_lock,
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


def test_postgresql_chain_append_uses_transaction_advisory_lock() -> None:
    session = Mock()
    session.get_bind.return_value.dialect.name = "postgresql"

    _acquire_chain_append_lock(session)

    statement, parameters = session.execute.call_args.args
    assert str(statement) == "SELECT pg_advisory_xact_lock(:lock_id)"
    assert parameters == {"lock_id": CHAIN_APPEND_LOCK_ID}


def test_sqlite_chain_append_does_not_request_postgresql_lock() -> None:
    session = Mock()
    session.get_bind.return_value.dialect.name = "sqlite"

    _acquire_chain_append_lock(session)

    session.execute.assert_not_called()


def test_physical_audit_predecessor_is_unique() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    key = "physical-audit-test-key-000000000000"
    with Session(engine) as session:
        first = append_physical_event(
            session,
            action="site.register",
            actor="operator-a",
            resource_type="physical-site",
            resource_id="hospital-a",
            outcome="accepted",
            hmac_key=key,
        )
        session.commit()
        assert first.previous_hash == "0" * 64

        session.add(
            PhysicalControlEvent(
                event_id="physical-event-fork",
                action="site.register",
                actor="operator-b",
                resource_type="physical-site",
                resource_id="hospital-b",
                outcome="accepted",
                previous_hash="0" * 64,
                event_hash="f" * 64,
                algorithm="HMAC-SHA256",
                key_id="test-key",
            )
        )
        with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
            session.commit()
