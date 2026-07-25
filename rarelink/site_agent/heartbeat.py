"""Pure mapping from local evidence to the central heartbeat API contract."""

from __future__ import annotations

import hashlib

from rarelink.site_agent.receipt import canonical_json
from rarelink.site_agent.schemas import HealthSnapshot, TaskRecord, TaskState

AGENT_VERSION = "0.2.0"
ACTIVE_STATES = {
    TaskState.STARTING,
    TaskState.RUNNING,
    TaskState.STOPPING,
    TaskState.RECOVERING,
}


def _check_status(health: HealthSnapshot, name: str) -> tuple[bool, str, dict]:
    check = health.checks.get(name)
    if check is None:
        return False, "UNKNOWN", {}
    return check.ok, check.status.upper()[:32], check.details


def _dependency_ready(health: HealthSnapshot, module: str) -> bool:
    check = health.checks.get("dependencies")
    if check is None or not check.ok:
        return False
    versions = check.details.get("versions", {})
    return isinstance(versions, dict) and module in versions


def to_central_heartbeat(
    *,
    heartbeat_id: str,
    health: HealthSnapshot,
    tasks: list[TaskRecord],
) -> dict[str, object]:
    """Return exactly the fields accepted by ``PhysicalSiteHeartbeat``."""
    active = [task for task in tasks if task.state in ACTIVE_STATES]
    current = max(active, key=lambda item: item.updated_at) if active else None
    gpu_ready, _, _ = _check_status(health, "gpu")
    data_ready, _, _ = _check_status(health, "dataset_manifest")
    _, certificate_status, _ = _check_status(health, "certificate")
    _, _, memory = _check_status(health, "memory")
    _, _, disk = _check_status(health, "disk")

    status = "TRAINING" if current else ("READY" if health.ready else "DEGRADED")
    base: dict[str, object] = {
        "heartbeat_id": heartbeat_id,
        "agent_version": AGENT_VERSION,
        "status": status,
        "certificate_status": certificate_status,
        "data_ready": data_ready,
        "gpu_ready": gpu_ready,
        "monai_ready": _dependency_ready(health, "monai"),
        "nvflare_ready": _dependency_ready(health, "nvflare"),
        "current_job_id": current.task_id if current else None,
        "current_round": current.round_id if current else 0,
        "total_rounds": max(current.total_rounds, current.round_id) if current else 0,
        "free_memory_percent": float(memory.get("free_percent", 0)),
        "free_disk_percent": float(disk.get("free_percent", 0)),
        # Pydantic serializes UTC datetimes in the central schema with ``Z``.
        # Sign that same wire representation so schema validation cannot change
        # the authenticated bytes between the Site Agent and coordinator.
        "captured_at": health.checked_at.isoformat().replace("+00:00", "Z"),
        "contains_patient_data": False,
    }
    receipt_source = {
        "site_health": health.model_dump(mode="json"),
        "current_task_receipt": current.receipt.payload_sha256 if current else None,
    }
    base["receipt_sha256"] = hashlib.sha256(canonical_json(receipt_source)).hexdigest()
    return base
