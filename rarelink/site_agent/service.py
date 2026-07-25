"""Idempotent task lifecycle orchestration for the hospital-local agent."""

from __future__ import annotations

import threading
from collections.abc import Callable

from rarelink.site_agent.executor import SiteTaskExecutor
from rarelink.site_agent.receipt import ReceiptSigner
from rarelink.site_agent.schemas import (
    TaskActionRequest,
    TaskActionResponse,
    TaskRecord,
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


class TaskService:
    def __init__(
        self,
        store: TaskStore,
        signer: ReceiptSigner,
        executor: SiteTaskExecutor,
    ) -> None:
        self.store = store
        self.signer = signer
        self.executor = executor
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
    ) -> TaskRecord:
        observed_at = utc_now()
        revision = (previous.revision + 1) if previous else 1
        total_rounds = request.total_rounds or (previous.total_rounds if previous else 0)
        receipt = self.signer.sign_task(
            event=event,
            task_id=request.task_id,
            round_id=request.round_id,
            total_rounds=total_rounds,
            contract_sha256=request.contract_sha256,
            state=state,
            revision=revision,
            issued_at=observed_at,
        )
        return TaskRecord(
            task_id=request.task_id,
            round_id=request.round_id,
            total_rounds=total_rounds,
            contract_sha256=request.contract_sha256,
            state=state,
            revision=revision,
            executor_ref=executor_ref if executor_ref is not None else (
                previous.executor_ref if previous else None
            ),
            error_code=error_code,
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
    ) -> TaskActionResponse:
        transition = self._record(
            request, transition_state, transition_event, previous=previous
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
            )
            self.store.put(failed)
            raise ExecutorActionError("site executor rejected the requested action") from exc
        completed = self._record(
            request,
            success_state,
            success_event,
            previous=transition,
            executor_ref=executor_ref,
        )
        self.store.put(completed)
        return TaskActionResponse(record=completed, idempotent_replay=False)

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
            seed = self._record(request, TaskState.STARTING, "start_requested")
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
            )
            self.store.put(running)
            return TaskActionResponse(record=running, idempotent_replay=False)

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
            self._check_contract(existing, request)
            if existing.state in {TaskState.RUNNING, TaskState.COMPLETED}:
                return TaskActionResponse(record=existing, idempotent_replay=True)
            if existing.state not in {TaskState.STOPPED, TaskState.FAILED}:
                raise TaskConflictError(f"cannot recover a task in {existing.state}")
            return self._execute(
                request=request,
                previous=existing,
                transition_state=TaskState.RECOVERING,
                success_state=TaskState.RUNNING,
                transition_event="recover_requested",
                success_event="recovered",
                action=self.executor.recover,
            )

    def reconcile_interrupted_transitions(self) -> int:
        """Fail closed after a process restart; an operator may then recover."""
        count = 0
        with self._lock:
            for existing in self.store.list():
                if existing.state not in {
                    TaskState.STARTING,
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
        return count
