"""SQLModel persistence adapter for the physical NVFLARE controller."""

from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import Session, select

from rarelink.domain import PhysicalJobStatus, utc_now
from rarelink.models import PhysicalFederationJob
from rarelink.services.physical_controller import (
    PhysicalJobRecord,
    PhysicalJobState,
    ValidatedJobBundle,
)

STATE_TO_MODEL = {
    PhysicalJobState.VALIDATED: PhysicalJobStatus.APPROVAL_PENDING,
    PhysicalJobState.SUBMITTED: PhysicalJobStatus.SUBMITTED,
    PhysicalJobState.WAITING_FOR_SITES: PhysicalJobStatus.WAITING_FOR_SITES,
    PhysicalJobState.RUNNING: PhysicalJobStatus.RUNNING,
    PhysicalJobState.COMPLETED: PhysicalJobStatus.COMPLETED,
    PhysicalJobState.FAILED: PhysicalJobStatus.FAILED,
    PhysicalJobState.ABORTED: PhysicalJobStatus.ABORTED,
}
MODEL_TO_STATE = {
    PhysicalJobStatus.DRAFT: PhysicalJobState.VALIDATED,
    PhysicalJobStatus.APPROVAL_PENDING: PhysicalJobState.VALIDATED,
    PhysicalJobStatus.SUBMITTED: PhysicalJobState.SUBMITTED,
    PhysicalJobStatus.WAITING_FOR_SITES: PhysicalJobState.WAITING_FOR_SITES,
    PhysicalJobStatus.RUNNING: PhysicalJobState.RUNNING,
    PhysicalJobStatus.COMPLETED: PhysicalJobState.COMPLETED,
    PhysicalJobStatus.FAILED: PhysicalJobState.FAILED,
    PhysicalJobStatus.ABORTED: PhysicalJobState.ABORTED,
}


class SqlPhysicalJobStore:
    """Persist safe controller state without exposing paths in public receipts."""

    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _record(model: PhysicalFederationJob) -> PhysicalJobRecord:
        sites = tuple(json.loads(model.expected_sites_json))
        if len(sites) != 3:
            raise ValueError("Physical job persistence requires exactly three expected sites")
        bundle = ValidatedJobBundle(
            directory=Path(model.job_directory),
            directory_name=Path(model.job_directory).name,
            bundle_sha256=model.bundle_sha256 or "",
            strategy=model.strategy,
            expected_sites=(str(sites[0]), str(sites[1]), str(sites[2])),
            total_rounds=model.total_rounds,
            local_epochs=model.local_epochs,
        )
        previous = tuple(json.loads(model.previous_external_job_ids_json))
        return PhysicalJobRecord(
            job_id=model.id,
            bundle=bundle,
            state=MODEL_TO_STATE[model.status],
            external_job_id=model.external_job_id,
            submit_token_sha256=model.submit_token_sha256,
            updated_at=model.updated_at,
            current_round=model.current_round,
            reported_sites=tuple(json.loads(model.connected_sites_json)),
            received_updates=model.received_updates,
            attempt=model.attempt,
            previous_external_job_ids=previous,
            global_model_path=(
                Path(model.global_model_path) if model.global_model_path else None
            ),
            global_model_sha256=model.global_model_sha256,
            error_code=model.error,
        )

    def get(self, job_id: str) -> PhysicalJobRecord | None:
        model = self.session.get(PhysicalFederationJob, job_id)
        return self._record(model) if model else None

    def save(self, record: PhysicalJobRecord) -> None:
        model = self.session.get(PhysicalFederationJob, record.job_id)
        if not model:
            model = PhysicalFederationJob(
                id=record.job_id,
                strategy=record.bundle.strategy,
                status=STATE_TO_MODEL[record.state],
                bundle_sha256=record.bundle.bundle_sha256,
                expected_sites_json=json.dumps(record.bundle.expected_sites),
                connected_sites_json="[]",
                total_rounds=record.bundle.total_rounds,
                local_epochs=record.bundle.local_epochs,
                quorum_required=3,
                job_directory=str(record.bundle.directory),
            )
        model.status = STATE_TO_MODEL[record.state]
        model.bundle_sha256 = record.bundle.bundle_sha256
        model.external_job_id = record.external_job_id
        model.submit_token_sha256 = record.submit_token_sha256
        model.current_round = record.current_round
        model.connected_sites_json = json.dumps(record.reported_sites)
        model.received_updates = record.received_updates
        model.attempt = record.attempt
        model.previous_external_job_ids_json = json.dumps(
            record.previous_external_job_ids
        )
        model.global_model_path = (
            str(record.global_model_path) if record.global_model_path else None
        )
        model.global_model_sha256 = record.global_model_sha256
        model.error = record.error_code
        model.updated_at = utc_now()
        if record.state is PhysicalJobState.COMPLETED:
            model.completed_at = utc_now()
        self.session.add(model)
        self.session.commit()

    def list(self) -> list[PhysicalJobRecord]:
        statement = select(PhysicalFederationJob).order_by(
            PhysicalFederationJob.created_at.desc()
        )
        return [self._record(model) for model in self.session.exec(statement).all()]
