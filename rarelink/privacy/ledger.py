"""Persistent, fail-closed DP budget accounting for physical federation jobs."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from rarelink.domain import utc_now
from rarelink.models import (
    PhysicalFederationJob,
    PhysicalPrivacyBudget,
    PhysicalPrivacySpend,
    PhysicalSite,
)

GENESIS_HASH = "0" * 64


class PrivacyBudgetError(ValueError):
    """The requested privacy operation violates the locked contract."""


@dataclass(frozen=True)
class PrivacySpendInput:
    job_id: str
    site_id: str
    round_number: int
    cumulative_epsilon: float
    delta: float
    accountant: str
    optimizer_steps: int


def _validate_budget(max_epsilon: float, delta: float) -> None:
    if not math.isfinite(max_epsilon) or max_epsilon <= 0:
        raise PrivacyBudgetError("max_epsilon must be finite and positive")
    if not math.isfinite(delta) or not 0 < delta < 1:
        raise PrivacyBudgetError("delta must be in (0, 1)")


def _public_budget(budget: PhysicalPrivacyBudget) -> dict[str, object]:
    return {
        "schema_version": "rarelink-privacy-budget-v1",
        "budget_id": budget.id,
        "job_id": budget.job_id,
        "contract_sha256": budget.contract_sha256,
        "max_epsilon": budget.max_epsilon,
        "delta": budget.delta,
        "consumed_epsilon": budget.consumed_epsilon,
        "remaining_epsilon": max(0.0, budget.max_epsilon - budget.consumed_epsilon),
        "status": budget.status,
        "ledger_head_sha256": budget.ledger_head_sha256,
        "patient_data_exported": False,
    }


class SqlPrivacyBudgetLedger:
    """Serialize DP spends in the same PostgreSQL transaction as budget enforcement."""

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        job_id: str,
        contract_sha256: str,
        max_epsilon: float,
        delta: float,
    ) -> dict[str, object]:
        _validate_budget(max_epsilon, delta)
        if len(contract_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in contract_sha256
        ):
            raise PrivacyBudgetError("contract_sha256 is invalid")
        if self.session.get(PhysicalFederationJob, job_id) is None:
            raise PrivacyBudgetError("Physical federation job does not exist")
        existing = self.session.exec(
            select(PhysicalPrivacyBudget).where(PhysicalPrivacyBudget.job_id == job_id)
        ).first()
        if existing:
            if (
                existing.contract_sha256 != contract_sha256
                or existing.max_epsilon != max_epsilon
                or existing.delta != delta
            ):
                raise PrivacyBudgetError("Privacy budget is already locked for this job")
            return _public_budget(existing)
        budget = PhysicalPrivacyBudget(
            job_id=job_id,
            contract_sha256=contract_sha256,
            max_epsilon=max_epsilon,
            delta=delta,
        )
        self.session.add(budget)
        self.session.commit()
        self.session.refresh(budget)
        return _public_budget(budget)

    def record(self, spend: PrivacySpendInput) -> dict[str, object]:
        if spend.round_number < 1:
            raise PrivacyBudgetError("round_number must be positive")
        if (
            not math.isfinite(spend.cumulative_epsilon)
            or spend.cumulative_epsilon < 0
        ):
            raise PrivacyBudgetError("cumulative_epsilon must be finite and non-negative")
        if spend.optimizer_steps < 1:
            raise PrivacyBudgetError("optimizer_steps must be positive")
        if spend.accountant != "rdp":
            raise PrivacyBudgetError("The locked accountant is rdp")
        if self.session.get(PhysicalSite, spend.site_id) is None:
            raise PrivacyBudgetError("Physical site does not exist")

        statement = (
            select(PhysicalPrivacyBudget)
            .where(PhysicalPrivacyBudget.job_id == spend.job_id)
            .with_for_update()
        )
        budget = self.session.exec(statement).first()
        if budget is None:
            raise PrivacyBudgetError("Privacy budget is not locked for this job")
        if budget.status != "ACTIVE":
            raise PrivacyBudgetError("Privacy budget is not active")
        if spend.delta != budget.delta:
            raise PrivacyBudgetError("Site delta differs from the locked contract")

        prior = self.session.exec(
            select(PhysicalPrivacySpend)
            .where(
                PhysicalPrivacySpend.budget_id == budget.id,
                PhysicalPrivacySpend.site_id == spend.site_id,
            )
            .order_by(PhysicalPrivacySpend.round_number.desc())
            .with_for_update()
        ).first()
        if prior and spend.round_number <= prior.round_number:
            raise PrivacyBudgetError("Duplicate or out-of-order privacy receipt rejected")
        if prior and spend.cumulative_epsilon < prior.cumulative_epsilon:
            raise PrivacyBudgetError("Cumulative epsilon cannot decrease")

        other_latest = list(
            self.session.exec(
                select(PhysicalPrivacySpend).where(
                    PhysicalPrivacySpend.budget_id == budget.id,
                    PhysicalPrivacySpend.site_id != spend.site_id,
                )
            ).all()
        )
        federation_epsilon = max(
            [spend.cumulative_epsilon]
            + [item.cumulative_epsilon for item in other_latest]
        )
        if federation_epsilon > budget.max_epsilon:
            budget.status = "EXHAUSTED"
            budget.updated_at = utc_now()
            self.session.add(budget)
            self.session.commit()
            raise PrivacyBudgetError("Privacy budget exceeded; further training is blocked")

        payload = {
            "budget_id": budget.id,
            "job_id": spend.job_id,
            "site_id": spend.site_id,
            "round_number": spend.round_number,
            "cumulative_epsilon": spend.cumulative_epsilon,
            "delta": spend.delta,
            "accountant": spend.accountant,
            "optimizer_steps": spend.optimizer_steps,
            "previous_hash": budget.ledger_head_sha256 or GENESIS_HASH,
        }
        receipt_sha256 = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        record = PhysicalPrivacySpend(
            **payload,
            receipt_sha256=receipt_sha256,
        )
        budget.consumed_epsilon = federation_epsilon
        budget.ledger_head_sha256 = receipt_sha256
        budget.updated_at = utc_now()
        self.session.add(record)
        self.session.add(budget)
        try:
            self.session.commit()
        except IntegrityError as error:
            self.session.rollback()
            raise PrivacyBudgetError("Duplicate privacy receipt rejected") from error
        return {
            **_public_budget(budget),
            "spend_id": record.id,
            "site_id": record.site_id,
            "round_number": record.round_number,
            "cumulative_epsilon": record.cumulative_epsilon,
            "accountant": record.accountant,
            "optimizer_steps": record.optimizer_steps,
            "receipt_sha256": record.receipt_sha256,
            "raw_gradient_exported": False,
        }
