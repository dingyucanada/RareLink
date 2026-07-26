"""SQLModel persistence adapter for the physical NVFLARE controller."""

from __future__ import annotations

import json
import re
from pathlib import Path

from sqlmodel import Session, select

from rarelink.domain import PhysicalJobStatus, utc_now
from rarelink.models import PhysicalFederationJob
from rarelink.privacy.physical_contract import (
    DP_STRATEGY,
    validate_physical_privacy_contract,
)
from rarelink.services.physical_controller import (
    PhysicalControllerError,
    PhysicalJobRecord,
    PhysicalJobState,
    ValidatedJobBundle,
    validate_exported_job,
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
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ERROR_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_.:-]{2,127}$")


class PhysicalStoreIntegrityError(RuntimeError):
    """Safe failure for a corrupt or incomplete physical job projection."""


class SqlPhysicalJobStore:
    """Persist safe controller state without exposing paths in public receipts."""

    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _json_string_list(
        raw: str,
        *,
        field_name: str,
        exact_length: int | None = None,
    ) -> tuple[str, ...]:
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise PhysicalStoreIntegrityError(
                f"Persisted physical job field {field_name} is invalid"
            ) from exc
        if (
            not isinstance(value, list)
            or any(not isinstance(item, str) or not item for item in value)
            or len(value) != len(set(value))
            or (exact_length is not None and len(value) != exact_length)
        ):
            raise PhysicalStoreIntegrityError(
                f"Persisted physical job field {field_name} is invalid"
            )
        return tuple(value)

    @staticmethod
    def _record(model: PhysicalFederationJob) -> PhysicalJobRecord:
        sites = SqlPhysicalJobStore._json_string_list(
            model.expected_sites_json,
            field_name="expected_sites_json",
            exact_length=3,
        )
        if not model.bundle_sha256 or not SHA256_RE.fullmatch(model.bundle_sha256):
            raise PhysicalStoreIntegrityError(
                "Persisted physical job bundle digest is invalid"
            )
        try:
            state = MODEL_TO_STATE[model.status]
        except KeyError as exc:
            raise PhysicalStoreIntegrityError(
                "Persisted physical job status is not supported"
            ) from exc
        reported_sites = SqlPhysicalJobStore._json_string_list(
            model.connected_sites_json,
            field_name="connected_sites_json",
        )
        if set(reported_sites) - set(sites):
            raise PhysicalStoreIntegrityError(
                "Persisted physical job contains an unexpected site identity"
            )
        previous = SqlPhysicalJobStore._json_string_list(
            model.previous_external_job_ids_json,
            field_name="previous_external_job_ids_json",
        )
        if model.submit_token_sha256 and not SHA256_RE.fullmatch(
            model.submit_token_sha256
        ):
            raise PhysicalStoreIntegrityError(
                "Persisted physical job submission token digest is invalid"
            )
        if model.error and not SAFE_ERROR_CODE_RE.fullmatch(model.error):
            raise PhysicalStoreIntegrityError(
                "Persisted physical job error code is invalid"
            )
        if model.strategy == DP_STRATEGY:
            try:
                bundle = validate_exported_job(Path(model.job_directory))
            except (OSError, PhysicalControllerError, ValueError) as exc:
                raise PhysicalStoreIntegrityError(
                    "Persisted DP-SGD job bundle cannot be revalidated"
                ) from exc
            if bundle.bundle_sha256 != model.bundle_sha256:
                raise PhysicalStoreIntegrityError(
                    "Persisted DP-SGD job bundle digest no longer matches"
                )
        else:
            bundle = ValidatedJobBundle(
                directory=Path(model.job_directory),
                directory_name=Path(model.job_directory).name,
                bundle_sha256=model.bundle_sha256,
                strategy=model.strategy,
                expected_sites=(str(sites[0]), str(sites[1]), str(sites[2])),
                total_rounds=model.total_rounds,
                local_epochs=model.local_epochs,
                privacy_contract=validate_physical_privacy_contract(
                    model.strategy,
                    None,
                ),
            )
        return PhysicalJobRecord(
            job_id=model.id,
            bundle=bundle,
            state=state,
            external_job_id=model.external_job_id,
            submit_token_sha256=model.submit_token_sha256,
            updated_at=model.updated_at,
            current_round=model.current_round,
            reported_sites=reported_sites,
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
        if not SHA256_RE.fullmatch(record.bundle.bundle_sha256):
            raise PhysicalStoreIntegrityError(
                "Physical job bundle digest is invalid"
            )
        if len(record.bundle.expected_sites) != 3 or len(
            set(record.bundle.expected_sites)
        ) != 3:
            raise PhysicalStoreIntegrityError(
                "Physical job requires three unique expected sites"
            )
        if set(record.reported_sites) - set(record.bundle.expected_sites):
            raise PhysicalStoreIntegrityError(
                "Physical job contains an unexpected site identity"
            )
        if record.submit_token_sha256 and not SHA256_RE.fullmatch(
            record.submit_token_sha256
        ):
            raise PhysicalStoreIntegrityError(
                "Physical job submission token digest is invalid"
            )
        if record.error_code and not SAFE_ERROR_CODE_RE.fullmatch(record.error_code):
            raise PhysicalStoreIntegrityError("Physical job error code is invalid")
        model = self.session.get(PhysicalFederationJob, record.job_id)
        if not model:
            model = PhysicalFederationJob(
                id=record.job_id,
                strategy=record.bundle.strategy,
                status=STATE_TO_MODEL[record.state],
                bundle_sha256=record.bundle.bundle_sha256,
                expected_sites_json=json.dumps(record.bundle.expected_sites),
                dataset_fingerprints_json="{}",
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
        else:
            model.completed_at = None
        self.session.add(model)
        self.session.commit()

    def list(self) -> list[PhysicalJobRecord]:
        statement = select(PhysicalFederationJob).order_by(
            PhysicalFederationJob.created_at.desc()
        )
        return [self._record(model) for model in self.session.exec(statement).all()]

    def find_by_submit_token_sha256(
        self,
        submit_token_sha256: str,
    ) -> PhysicalJobRecord | None:
        if not SHA256_RE.fullmatch(submit_token_sha256):
            raise PhysicalStoreIntegrityError(
                "Submission token digest lookup is invalid"
            )
        statement = select(PhysicalFederationJob).where(
            PhysicalFederationJob.submit_token_sha256 == submit_token_sha256
        )
        models = self.session.exec(statement).all()
        if len(models) > 1:
            raise PhysicalStoreIntegrityError(
                "Submission token digest is bound to multiple physical jobs"
            )
        return self._record(models[0]) if models else None
