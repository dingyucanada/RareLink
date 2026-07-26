"""Idempotent task lifecycle orchestration for the hospital-local agent."""

from __future__ import annotations

import threading
from collections.abc import Callable

from rarelink.site_agent.executor import SiteTaskExecutor
from rarelink.site_agent.receipt import ReceiptSigner
from rarelink.site_agent.schemas import (
    CheckpointMetadata,
    HealthSnapshot,
    TaskActionRequest,
    TaskActionResponse,
    TaskRecord,
    TaskStage,
    TaskState,
    utc_now,
)
from rarelink.site_agent.store import TaskStore


class TaskConflictError(ValueError):
    pass


class TaskNotFoundError(LookupError):
    pass


class ExecutorActionError(RuntimeError):
    pass


class PreflightFailedError(RuntimeError):
    pass


class CheckpointPreconditionError(RuntimeError):
    pass


STAGE_BY_STATE = {
    TaskState.STARTING: TaskStage.STARTING,
    TaskState.RUNNING: TaskStage.TRAINING,
    TaskState.PAUSING: TaskStage.PAUSING,
    TaskState.PAUSED: TaskStage.PAUSED,
    TaskState.STOPPING: TaskStage.STOPPING,
    TaskState.STOPPED: TaskStage.STOPPED,
    TaskState.RECOVERING: TaskStage.RECOVERING,
    TaskState.COMPLETED: TaskStage.COMPLETED,
    TaskState.FAILED: TaskStage.FAILED,
}


class TaskService:
    def __init__(
        self,
        store: TaskStore,
        signer: ReceiptSigner,
        executor: SiteTaskExecutor,
        readiness_guard: Callable[[], bool] | None = None,
        resource_probe: Callable[[], HealthSnapshot] | None = None,
        checkpoint_provider: Callable[[TaskRecord], CheckpointMetadata] | None = None,
        require_checkpoint_for_pause: bool = False,
        require_checkpoint_for_recover: bool = False,
    ) -> None:
        self.store = store
        self.signer = signer
        self.executor = executor
        self.readiness_guard = readiness_guard
        self.resource_probe = resource_probe
        self.checkpoint_provider = checkpoint_provider
        self.require_checkpoint_for_pause = require_checkpoint_for_pause
        self.require_checkpoint_for_recover = require_checkpoint_for_recover
        self._lock = threading.RLock()

    def _record(
        self,
        request: TaskActionRequest,
        state: TaskState,
        event: str,
        *,
        previous: TaskRecord | None = None,
        executor_ref: str | None = None,
        error_code: str | None = None,
        resource_status: dict[str, str] | None = None,
        checkpoint: CheckpointMetadata | None = None,
    ) -> TaskRecord:
        observed_at = utc_now()
        revision = (previous.revision + 1) if previous else 1
        total_rounds = request.total_rounds or (previous.total_rounds if previous else 0)
        active_runtime = previous.active_runtime_seconds if previous else 0
        if previous and previous.state == TaskState.RUNNING and previous.active_since:
            active_runtime += max(
                0, (observed_at - previous.active_since).total_seconds()
            )
        active_since = (
            previous.active_since
            if previous and previous.state == TaskState.RUNNING and state == TaskState.RUNNING
            else observed_at if state == TaskState.RUNNING else None
        )
        verified_checkpoint = checkpoint or (previous.checkpoint if previous else None)
        receipt = self.signer.sign_task(
            event=event,
            task_id=request.task_id,
            round_id=request.round_id,
            total_rounds=total_rounds,
            contract_sha256=request.contract_sha256,
            state=state,
            revision=revision,
            checkpoint_sha256=(
                verified_checkpoint.checkpoint_sha256 if verified_checkpoint else None
            ),
            issued_at=observed_at,
        )
        return TaskRecord(
            task_id=request.task_id,
            round_id=request.round_id,
            total_rounds=total_rounds,
            contract_sha256=request.contract_sha256,
            state=state,
            training_stage=STAGE_BY_STATE[state],
            revision=revision,
            executor_ref=executor_ref if executor_ref is not None else (
                previous.executor_ref if previous else None
            ),
            error_code=error_code,
            active_runtime_seconds=active_runtime,
            active_since=active_since,
            resource_status=(
                resource_status
                if resource_status is not None
                else previous.resource_status if previous else {}
            ),
            checkpoint=verified_checkpoint,
            created_at=previous.created_at if previous else observed_at,
            updated_at=observed_at,
            receipt=receipt,
        )

    @staticmethod
    def _check_contract(existing: TaskRecord, request: TaskActionRequest) -> None:
        if existing.contract_sha256 != request.contract_sha256:
            raise TaskConflictError(
                "task_id and round_id already belong to a different research contract"
            )
        if (
            existing.total_rounds
            and request.total_rounds
            and existing.total_rounds != request.total_rounds
        ):
            raise TaskConflictError("total_rounds conflicts with the existing task round")

    def _stored_record_is_authentic(self, record: TaskRecord) -> bool:
        receipt = record.receipt
        checkpoint_sha256 = (
            record.checkpoint.checkpoint_sha256 if record.checkpoint else None
        )
        return (
            self.signer.verify_task(receipt)
            and receipt.task_id == record.task_id
            and receipt.round_id == record.round_id
            and receipt.total_rounds == record.total_rounds
            and receipt.contract_sha256 == record.contract_sha256
            and receipt.state == record.state
            and receipt.revision == record.revision
            and receipt.issued_at == record.updated_at
            and receipt.checkpoint_sha256 == checkpoint_sha256
        )

    def _execute(
        self,
        *,
        request: TaskActionRequest,
        previous: TaskRecord,
        transition_state: TaskState,
        success_state: TaskState,
        transition_event: str,
        success_event: str,
        action: Callable[[TaskRecord], str | None],
        resource_status: dict[str, str] | None = None,
        checkpoint: CheckpointMetadata | None = None,
    ) -> TaskActionResponse:
        transition = self._record(
            request,
            transition_state,
            transition_event,
            previous=previous,
            resource_status=resource_status,
            checkpoint=checkpoint,
        )
        self.store.put(transition)
        try:
            executor_ref = action(transition)
        except Exception as exc:
            failed = self._record(
                request,
                TaskState.FAILED,
                f"{transition_event}_failed",
                previous=transition,
                error_code=type(exc).__name__,
                checkpoint=checkpoint,
            )
            self.store.put(failed)
            raise ExecutorActionError("site executor rejected the requested action") from exc
        completed = self._record(
            request,
            success_state,
            success_event,
            previous=transition,
            executor_ref=executor_ref,
            checkpoint=checkpoint,
        )
        self.store.put(completed)
        return TaskActionResponse(record=completed, idempotent_replay=False)

    def _resource_status(self) -> dict[str, str]:
        if self.resource_probe is None:
            return {}
        try:
            snapshot = self.resource_probe()
        except Exception:
            return {"probe": "failed"}
        return {name: check.status for name, check in sorted(snapshot.checks.items())}

    def _require_ready(
        self,
        request: TaskActionRequest,
        *,
        previous: TaskRecord | None = None,
    ) -> dict[str, str]:
        resource_status = self._resource_status()
        if self.readiness_guard is None:
            return resource_status
        try:
            ready = self.readiness_guard()
        except Exception:
            ready = False
        if ready:
            return resource_status
        failed = self._record(
            request,
            TaskState.FAILED,
            "preflight_failed",
            previous=previous,
            error_code="PreflightFailed",
            resource_status=resource_status,
        )
        self.store.put(failed)
        raise PreflightFailedError("site resource and security preflight did not pass")

    def _verified_checkpoint(
        self,
        task: TaskRecord,
        *,
        required: bool,
    ) -> CheckpointMetadata | None:
        if self.checkpoint_provider is None:
            if required:
                raise CheckpointPreconditionError(
                    "a verified local checkpoint is required for this action"
                )
            return task.checkpoint
        try:
            checkpoint = self.checkpoint_provider(task)
        except Exception as exc:
            if required:
                raise CheckpointPreconditionError(
                    "the local checkpoint receipt did not verify"
                ) from exc
            return task.checkpoint
        if (
            checkpoint.task_id != task.task_id
            or checkpoint.round_id != task.round_id
            or checkpoint.contract_sha256 != task.contract_sha256
        ):
            raise CheckpointPreconditionError(
                "the local checkpoint receipt does not match this task"
            )
        if (
            task.checkpoint
            and checkpoint.checkpoint_sha256 != task.checkpoint.checkpoint_sha256
        ):
            raise CheckpointPreconditionError(
                "the local checkpoint no longer matches the previously signed task state"
            )
        return checkpoint

    def list_tasks(self) -> list[TaskRecord]:
        observed_at = utc_now()
        current_resources = self._resource_status()
        records: list[TaskRecord] = []
        for record in self.store.list():
            active_runtime = record.active_runtime_seconds
            if record.state == TaskState.RUNNING and record.active_since:
                active_runtime += max(
                    0, (observed_at - record.active_since).total_seconds()
                )
            records.append(
                record.model_copy(
                    update={
                        "active_runtime_seconds": active_runtime,
                        "resource_status": current_resources or record.resource_status,
                    }
                )
            )
        return records

    def start(self, request: TaskActionRequest) -> TaskActionResponse:
        with self._lock:
            existing = self.store.get(request.task_id, request.round_id)
            if existing:
                self._check_contract(existing, request)
                if existing.state in {
                    TaskState.STARTING,
                    TaskState.RUNNING,
                    TaskState.COMPLETED,
                }:
                    return TaskActionResponse(record=existing, idempotent_replay=True)
                raise TaskConflictError(
                    f"cannot start a task in {existing.state}; "
                    "use recover for a stopped/failed task"
                )
            resource_status = self._require_ready(request)
            seed = self._record(
                request,
                TaskState.STARTING,
                "start_requested",
                resource_status=resource_status,
            )
            self.store.put(seed)
            try:
                executor_ref = self.executor.start(seed)
            except Exception as exc:
                failed = self._record(
                    request,
                    TaskState.FAILED,
                    "start_failed",
                    previous=seed,
                    error_code=type(exc).__name__,
                )
                self.store.put(failed)
                raise ExecutorActionError("site executor rejected the requested action") from exc
            running = self._record(
                request,
                TaskState.RUNNING,
                "started",
                previous=seed,
                executor_ref=executor_ref,
                resource_status=resource_status,
            )
            self.store.put(running)
            return TaskActionResponse(record=running, idempotent_replay=False)

    def pause(self, request: TaskActionRequest) -> TaskActionResponse:
        with self._lock:
            existing = self.store.get(request.task_id, request.round_id)
            if not existing:
                raise TaskNotFoundError("task round not found")
            self._check_contract(existing, request)
            if existing.state == TaskState.PAUSED:
                return TaskActionResponse(record=existing, idempotent_replay=True)
            if existing.state != TaskState.RUNNING:
                raise TaskConflictError(f"cannot pause a task in {existing.state}")
            checkpoint = self._verified_checkpoint(
                existing,
                required=self.require_checkpoint_for_pause,
            )
            pause_action = getattr(self.executor, "pause", None)
            if not callable(pause_action):
                raise ExecutorActionError("site executor does not support pause")
            return self._execute(
                request=request,
                previous=existing,
                transition_state=TaskState.PAUSING,
                success_state=TaskState.PAUSED,
                transition_event="pause_requested",
                success_event="paused",
                action=pause_action,
                resource_status=self._resource_status(),
                checkpoint=checkpoint,
            )

    def stop(self, request: TaskActionRequest) -> TaskActionResponse:
        with self._lock:
            existing = self.store.get(request.task_id, request.round_id)
            if not existing:
                raise TaskNotFoundError("task round not found")
            self._check_contract(existing, request)
            if existing.state in {TaskState.STOPPED, TaskState.COMPLETED}:
                return TaskActionResponse(record=existing, idempotent_replay=True)
            return self._execute(
                request=request,
                previous=existing,
                transition_state=TaskState.STOPPING,
                success_state=TaskState.STOPPED,
                transition_event="stop_requested",
                success_event="stopped",
                action=self.executor.stop,
            )

    def recover(self, request: TaskActionRequest) -> TaskActionResponse:
        with self._lock:
            existing = self.store.get(request.task_id, request.round_id)
            if not existing:
                raise TaskNotFoundError("task round not found")
            if not self._stored_record_is_authentic(existing):
                raise CheckpointPreconditionError(
                    "the stored task receipt did not verify"
                )
            self._check_contract(existing, request)
            if existing.state in {TaskState.RUNNING, TaskState.COMPLETED}:
                return TaskActionResponse(record=existing, idempotent_replay=True)
            if existing.state not in {
                TaskState.STOPPED,
                TaskState.PAUSED,
                TaskState.FAILED,
            }:
                raise TaskConflictError(f"cannot recover a task in {existing.state}")
            resource_status = self._require_ready(request, previous=existing)
            checkpoint_required = self.require_checkpoint_for_recover and (
                existing.state == TaskState.PAUSED
                or existing.executor_ref is not None
                or existing.active_runtime_seconds > 0
            )
            checkpoint = self._verified_checkpoint(
                existing,
                required=checkpoint_required,
            )
            action = self.executor.recover
            if existing.state == TaskState.PAUSED:
                resume_action = getattr(self.executor, "resume", None)
                if not callable(resume_action):
                    raise ExecutorActionError("site executor does not support resume")
                action = resume_action
            return self._execute(
                request=request,
                previous=existing,
                transition_state=TaskState.RECOVERING,
                success_state=TaskState.RUNNING,
                transition_event="recover_requested",
                success_event="recovered",
                action=action,
                resource_status=resource_status,
                checkpoint=checkpoint,
            )

    def reconcile_interrupted_transitions(self) -> int:
        """Fail closed after a process restart; an operator may then recover."""
        count = 0
        with self._lock:
            for existing in self.store.list():
                if self._stored_record_is_authentic(existing):
                    continue
                request = TaskActionRequest(
                    task_id=existing.task_id,
                    round_id=existing.round_id,
                    total_rounds=existing.total_rounds,
                    contract_sha256=existing.contract_sha256,
                )
                failed = self._record(
                    request,
                    TaskState.FAILED,
                    "invalid_stored_receipt",
                    previous=existing,
                    error_code="InvalidStoredReceipt",
                )
                self.store.put(failed)
                count += 1
            for existing in self.store.list():
                if existing.state not in {
                    TaskState.STARTING,
                    TaskState.PAUSING,
                    TaskState.STOPPING,
                    TaskState.RECOVERING,
                }:
                    continue
                request = TaskActionRequest(
                    task_id=existing.task_id,
                    round_id=existing.round_id,
                    total_rounds=existing.total_rounds,
                    contract_sha256=existing.contract_sha256,
                )
                failed = self._record(
                    request,
                    TaskState.FAILED,
                    "agent_restart_during_transition",
                    previous=existing,
                    error_code="InterruptedTransition",
                )
                self.store.put(failed)
                count += 1
            inspector = getattr(self.executor, "is_running", None)
            if callable(inspector):
                for existing in self.store.list():
                    if existing.state != TaskState.RUNNING:
                        continue
                    try:
                        running = inspector(existing)
                    except Exception:
                        running = False
                    if running:
                        continue
                    request = TaskActionRequest(
                        task_id=existing.task_id,
                        round_id=existing.round_id,
                        total_rounds=existing.total_rounds,
                        contract_sha256=existing.contract_sha256,
                    )
                    failed = self._record(
                        request,
                        TaskState.FAILED,
                        "executor_not_running_after_restart",
                        previous=existing,
                        error_code="ExecutorNotRunningAfterRestart",
                    )
                    self.store.put(failed)
                    count += 1
        return count
