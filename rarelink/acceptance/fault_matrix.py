"""Deterministic failure injection at RareLink's reviewed component boundaries."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rarelink.security.update_guard import (
    ModelUpdateEnvelope,
    SQLiteReplayRegistry,
    UpdateGuardError,
    UpdateGuardPolicy,
    guard_model_update,
)
from rarelink.site_agent.forwarder import BackoffPolicy, HeartbeatOutbox
from rarelink.site_agent.receipt import ReceiptSigner
from rarelink.site_agent.schemas import (
    CheckResult,
    HealthSnapshot,
    TaskActionRequest,
    TaskRecord,
    TaskState,
)
from rarelink.site_agent.service import PreflightFailedError, TaskService
from rarelink.site_agent.store import TaskStore

SITES = frozenset({"hospital-a", "hospital-b", "hospital-c"})
CONTRACT = "c" * 64


class ProbeExecutor:
    """In-memory action boundary; no shell, service, or training process is invoked."""

    def __init__(self, *, running: bool = True) -> None:
        self.running = running
        self.calls: list[str] = []

    def _action(self, action: str) -> str:
        self.calls.append(action)
        return "fault-injection-executor"

    def start(self, task: TaskRecord) -> str:
        return self._action("start")

    def stop(self, task: TaskRecord) -> str:
        return self._action("stop")

    def pause(self, task: TaskRecord) -> str:
        return self._action("pause")

    def resume(self, task: TaskRecord) -> str:
        return self._action("resume")

    def recover(self, task: TaskRecord) -> str:
        return self._action("recover")

    def is_running(self, task: TaskRecord) -> bool:
        return self.running


def _health(*, failed_check: str | None = None) -> HealthSnapshot:
    checks = {
        name: CheckResult(ok=True, status="ready")
        for name in (
            "gpu",
            "memory",
            "disk",
            "cpu",
            "certificate",
            "dependencies",
            "dataset_manifest",
            "startup_kit",
        )
    }
    if failed_check:
        checks[failed_check] = CheckResult(ok=False, status="injected_failure")
    return HealthSnapshot(
        ready=failed_check is None,
        checked_at=datetime.now(UTC),
        checks=checks,
    )


def _heartbeat_envelope() -> dict[str, Any]:
    payload = {
        "heartbeat_id": "heartbeat-fault-matrix-001",
        "agent_version": "0.2.0",
        "status": "READY",
        "certificate_status": "VALID",
        "data_ready": True,
        "gpu_ready": True,
        "monai_ready": True,
        "nvflare_ready": True,
        "current_job_id": None,
        "current_round": 0,
        "total_rounds": 0,
        "free_memory_percent": 70.0,
        "free_disk_percent": 60.0,
        "receipt_sha256": "d" * 64,
        "captured_at": datetime.now(UTC).isoformat(),
        "contains_patient_data": False,
    }
    return {
        "schema_version": "rarelink-site-heartbeat-v1",
        "site_id": "hospital-a",
        "timestamp": 1_700_000_000,
        "heartbeat_id": payload["heartbeat_id"],
        "payload": payload,
        "payload_sha256": "e" * 64,
        "algorithm": "HMAC-SHA256",
        "key_id": "fault-matrix-key",
        "signature": "f" * 64,
    }


def _scenario(
    scenario_id: str,
    *,
    passed: bool,
    expected_behavior: str,
    observed_behavior: str,
) -> dict[str, Any]:
    material = (
        f"{scenario_id}\x00{passed}\x00{expected_behavior}\x00{observed_behavior}"
    ).encode()
    return {
        "scenario_id": scenario_id,
        "passed": passed,
        "injection_boundary": "isolated component state",
        "expected_behavior": expected_behavior,
        "observed_behavior": observed_behavior,
        "receipt_sha256": hashlib.sha256(material).hexdigest(),
        "patient_data_used": False,
        "secret_exported": False,
        "local_path_exported": False,
    }


def _network_outage_scenario(root: Path) -> dict[str, Any]:
    outbox_path = root / "heartbeat-outbox.sqlite3"
    outbox = HeartbeatOutbox(
        outbox_path,
        BackoffPolicy(base_seconds=1, maximum_seconds=4),
    )
    envelope = _heartbeat_envelope()
    outbox.enqueue(envelope)
    delay = outbox.record_failure(100)
    restarted = HeartbeatOutbox(
        outbox_path,
        BackoffPolicy(base_seconds=1, maximum_seconds=4),
    )
    persisted = restarted.state().pending_envelope
    restarted.record_accepted(str(envelope["heartbeat_id"]))
    passed = (
        delay == 1
        and isinstance(persisted, dict)
        and persisted["heartbeat_id"] == envelope["heartbeat_id"]
        and restarted.state().pending_envelope is None
    )
    return _scenario(
        "network-outage-reconnect",
        passed=passed,
        expected_behavior="persist one signed heartbeat, back off, and clear only after acceptance",
        observed_behavior="pending envelope survived reconstruction and was acknowledged once",
    )


def _restart_recovery_scenario(root: Path) -> dict[str, Any]:
    store = TaskStore(root / "task-state.sqlite3")
    signer = ReceiptSigner("hospital-a", "fault-matrix-signing-key-000000000000")
    first_executor = ProbeExecutor()
    first = TaskService(
        store,
        signer,
        first_executor,
        readiness_guard=lambda: True,
        resource_probe=lambda: _health(),
    )
    request = TaskActionRequest(
        task_id="physical-job-fault-matrix",
        round_id=2,
        total_rounds=5,
        contract_sha256=CONTRACT,
    )
    first.start(request)
    restarted_executor = ProbeExecutor(running=False)
    restarted = TaskService(
        TaskStore(root / "task-state.sqlite3"),
        signer,
        restarted_executor,
        readiness_guard=lambda: True,
        resource_probe=lambda: _health(),
    )
    reconciled = restarted.reconcile_interrupted_transitions()
    failed = restarted.store.get(request.task_id, request.round_id)
    recovered = restarted.recover(request)
    replay = restarted.recover(request)
    passed = (
        first_executor.calls == ["start"]
        and reconciled == 1
        and failed is not None
        and failed.state == TaskState.FAILED
        and failed.error_code == "ExecutorNotRunningAfterRestart"
        and recovered.record.state == TaskState.RUNNING
        and replay.idempotent_replay is True
        and restarted_executor.calls == ["recover"]
    )
    return _scenario(
        "agent-restart-recovery",
        passed=passed,
        expected_behavior="fail closed, require recover, and never duplicate start/recover",
        observed_behavior="persisted task failed closed and one recovery restored RUNNING",
    )


def _preflight_scenario(root: Path, failed_check: str) -> dict[str, Any]:
    executor = ProbeExecutor()
    service = TaskService(
        TaskStore(root / f"{failed_check}-state.sqlite3"),
        ReceiptSigner(
            "hospital-a",
            f"fault-matrix-{failed_check}-signing-key-000000000",
        ),
        executor,
        readiness_guard=lambda: False,
        resource_probe=lambda: _health(failed_check=failed_check),
    )
    request = TaskActionRequest(
        task_id=f"physical-job-{failed_check}-fault",
        round_id=1,
        total_rounds=5,
        contract_sha256=CONTRACT,
    )
    blocked = False
    try:
        service.start(request)
    except PreflightFailedError:
        blocked = True
    record = service.store.get(request.task_id, request.round_id)
    return _scenario(
        f"{failed_check}-preflight-block",
        passed=(
            blocked
            and executor.calls == []
            and record is not None
            and record.state == TaskState.FAILED
            and record.error_code == "PreflightFailed"
        ),
        expected_behavior="block training before executor invocation",
        observed_behavior="preflight stored FAILED and executor remained untouched",
    )


def _update_replay_scenarios(root: Path) -> list[dict[str, Any]]:
    policy = UpdateGuardPolicy(
        expected_sites=SITES,
        max_l2_norm=5.0,
        minimum_sample_count=2,
    )
    registry = SQLiteReplayRegistry(root / "update-replay.sqlite3")
    envelope = ModelUpdateEnvelope(
        job_id="physical-job-fault-matrix",
        site_id="hospital-a",
        round_number=2,
        nonce="update-nonce-001",
        sample_count=8,
        tensors={"weight": [6.0, 8.0]},
    )
    accepted = guard_model_update(
        envelope,
        expected_round=2,
        policy=policy,
        replay_registry=registry,
    )
    duplicate_blocked = False
    try:
        guard_model_update(
            envelope,
            expected_round=2,
            policy=policy,
            replay_registry=SQLiteReplayRegistry(root / "update-replay.sqlite3"),
        )
    except UpdateGuardError as exc:
        duplicate_blocked = "Duplicate" in str(exc)
    late_blocked = False
    try:
        guard_model_update(
            ModelUpdateEnvelope(
                **{
                    **envelope.__dict__,
                    "round_number": 1,
                    "nonce": "update-nonce-late",
                }
            ),
            expected_round=2,
            policy=policy,
            replay_registry=registry,
        )
    except UpdateGuardError as exc:
        late_blocked = "Late or future-round" in str(exc)
    return [
        _scenario(
            "duplicate-update-rejected",
            passed=accepted.receipt["accepted"] is True and duplicate_blocked,
            expected_behavior="durable replay key accepts exactly one site-round nonce",
            observed_behavior="first update accepted and reconstructed registry rejected replay",
        ),
        _scenario(
            "late-update-rejected",
            passed=late_blocked,
            expected_behavior="reject updates whose Round ID differs from the active round",
            observed_behavior="old-round update was rejected before aggregation",
        ),
    ]


def run_fault_injection_matrix(root: Path) -> dict[str, Any]:
    """Run bounded synthetic failures without networking, shell, or medical data."""
    root.mkdir(parents=True, exist_ok=True)
    scenarios = [
        _network_outage_scenario(root),
        _restart_recovery_scenario(root),
        _preflight_scenario(root, "gpu"),
        _preflight_scenario(root, "disk"),
        _preflight_scenario(root, "certificate"),
        *_update_replay_scenarios(root),
    ]
    passed = len(scenarios) == 7 and all(item["passed"] for item in scenarios)
    canonical = json.dumps(
        [
            {
                "scenario_id": item["scenario_id"],
                "receipt_sha256": item["receipt_sha256"],
            }
            for item in scenarios
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        "schema_version": "rarelink-fault-injection-matrix-v1",
        "mode": "isolated-component-injection",
        "passed": passed,
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "matrix_sha256": hashlib.sha256(canonical).hexdigest(),
        "medical_data_used": False,
        "credentials_used": False,
        "shell_commands_executed": False,
        "physical_devices_claimed": False,
        "claim_boundary": (
            "This matrix proves reviewed failure semantics at isolated component boundaries. "
            "It does not replace cable-pull, process-kill, certificate-revocation, or "
            "disk-exhaustion exercises on three physical DGX Spark devices."
        ),
    }
