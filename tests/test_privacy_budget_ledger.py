from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from rarelink.models import PhysicalFederationJob, PhysicalSite
from rarelink.privacy.ledger import (
    PrivacyBudgetError,
    PrivacySpendInput,
    SqlPrivacyBudgetLedger,
)


@pytest.fixture
def session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'privacy.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as database:
        database.add(
            PhysicalFederationJob(
                id="job-001",
                strategy="fedavg_dpsgd",
                expected_sites_json=json.dumps(["hospital-a", "hospital-b", "hospital-c"]),
                total_rounds=5,
                local_epochs=1,
                quorum_required=3,
                job_directory="/internal/job",
            )
        )
        for site_id in ("hospital-a", "hospital-b", "hospital-c"):
            database.add(
                PhysicalSite(
                    site_id=site_id,
                    display_name=site_id,
                    organization="test-only",
                )
            )
        database.commit()
        yield database


def spend(site: str, round_number: int, epsilon: float) -> PrivacySpendInput:
    return PrivacySpendInput(
        job_id="job-001",
        site_id=site,
        round_number=round_number,
        cumulative_epsilon=epsilon,
        delta=1e-5,
        accountant="rdp",
        optimizer_steps=round_number * 12,
    )


def test_budget_uses_max_cumulative_site_epsilon_and_hash_chain(session: Session) -> None:
    ledger = SqlPrivacyBudgetLedger(session)
    contract_sha = hashlib.sha256(b"locked-contract").hexdigest()
    created = ledger.create(
        job_id="job-001",
        contract_sha256=contract_sha,
        max_epsilon=4.0,
        delta=1e-5,
    )
    first = ledger.record(spend("hospital-a", 1, 1.2))
    second = ledger.record(spend("hospital-b", 1, 0.9))
    third = ledger.record(spend("hospital-a", 2, 2.1))

    assert created["consumed_epsilon"] == 0.0
    assert first["consumed_epsilon"] == 1.2
    assert second["consumed_epsilon"] == 1.2
    assert third["consumed_epsilon"] == 2.1
    assert third["remaining_epsilon"] == pytest.approx(1.9)
    assert third["ledger_head_sha256"] == third["receipt_sha256"]
    assert third["raw_gradient_exported"] is False


def test_budget_is_immutable_and_rejects_replay(session: Session) -> None:
    ledger = SqlPrivacyBudgetLedger(session)
    contract_sha = hashlib.sha256(b"locked-contract").hexdigest()
    ledger.create(
        job_id="job-001",
        contract_sha256=contract_sha,
        max_epsilon=4.0,
        delta=1e-5,
    )
    ledger.record(spend("hospital-a", 1, 1.0))
    with pytest.raises(PrivacyBudgetError, match="Duplicate or out-of-order"):
        ledger.record(spend("hospital-a", 1, 1.0))
    with pytest.raises(PrivacyBudgetError, match="already locked"):
        ledger.create(
            job_id="job-001",
            contract_sha256=contract_sha,
            max_epsilon=9.0,
            delta=1e-5,
        )


def test_budget_exhaustion_fails_closed(session: Session) -> None:
    ledger = SqlPrivacyBudgetLedger(session)
    ledger.create(
        job_id="job-001",
        contract_sha256=hashlib.sha256(b"contract").hexdigest(),
        max_epsilon=2.0,
        delta=1e-5,
    )

    with pytest.raises(PrivacyBudgetError, match="exceeded"):
        ledger.record(spend("hospital-a", 1, 2.1))
    with pytest.raises(PrivacyBudgetError, match="not active"):
        ledger.record(spend("hospital-b", 1, 0.5))


@pytest.mark.parametrize(
    "invalid",
    [
        PrivacySpendInput("job-001", "hospital-a", 0, 0.2, 1e-5, "rdp", 1),
        PrivacySpendInput("job-001", "hospital-a", 1, -0.2, 1e-5, "rdp", 1),
        PrivacySpendInput("job-001", "hospital-a", 1, 0.2, 1e-4, "rdp", 1),
        PrivacySpendInput("job-001", "hospital-a", 1, 0.2, 1e-5, "prv", 1),
    ],
)
def test_budget_rejects_contract_mismatch(
    session: Session,
    invalid: PrivacySpendInput,
) -> None:
    ledger = SqlPrivacyBudgetLedger(session)
    ledger.create(
        job_id="job-001",
        contract_sha256=hashlib.sha256(b"contract").hexdigest(),
        max_epsilon=2.0,
        delta=1e-5,
    )
    with pytest.raises(PrivacyBudgetError):
        ledger.record(invalid)
