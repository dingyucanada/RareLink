"""Local checkpoint integrity verification without exporting model paths."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rarelink.site_agent.pki import public_path_secure
from rarelink.site_agent.schemas import CheckpointMetadata, TaskRecord, utc_now


class CheckpointValidationError(ValueError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checkpoint_receipt(
    *,
    receipt_path: Path,
    checkpoint_root: Path,
    task: TaskRecord,
) -> CheckpointMetadata:
    """Verify one model checkpoint; no medical image or private key is accessed."""
    if (
        receipt_path.is_symlink()
        or not receipt_path.is_file()
        or not public_path_secure(receipt_path, receipt_path.parent)
    ):
        raise CheckpointValidationError("checkpoint receipt is unavailable or insecure")
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CheckpointValidationError("checkpoint receipt is invalid") from exc
    if not isinstance(payload, dict):
        raise CheckpointValidationError("checkpoint receipt is invalid")
    required = {
        "schema_version",
        "checkpoint_id",
        "task_id",
        "round_id",
        "contract_sha256",
        "checkpoint_file",
        "checkpoint_sha256",
        "size_bytes",
        "created_at",
        "contains_patient_data",
        "path_exported",
    }
    if set(payload) != required:
        raise CheckpointValidationError("checkpoint receipt fields are not allow-listed")
    if (
        payload.get("schema_version") != "rarelink-checkpoint-receipt-v1"
        or payload.get("task_id") != task.task_id
        or payload.get("round_id") != task.round_id
        or payload.get("contract_sha256") != task.contract_sha256
        or payload.get("contains_patient_data") is not False
        or payload.get("path_exported") is not False
    ):
        raise CheckpointValidationError("checkpoint receipt does not match the task")
    relative = payload.get("checkpoint_file")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise CheckpointValidationError("checkpoint file reference is invalid")
    try:
        root = checkpoint_root.resolve(strict=True)
        unresolved_checkpoint = root / relative
        if not public_path_secure(unresolved_checkpoint, root):
            raise CheckpointValidationError(
                "checkpoint file is outside the approved store"
            )
        checkpoint_path = unresolved_checkpoint.resolve(strict=True)
    except OSError as exc:
        raise CheckpointValidationError("checkpoint file is unavailable") from exc
    if (
        not checkpoint_path.is_relative_to(root)
        or not checkpoint_path.is_file()
    ):
        raise CheckpointValidationError("checkpoint file is outside the approved store")
    size_bytes = checkpoint_path.stat().st_size
    if size_bytes != payload.get("size_bytes") or size_bytes < 1:
        raise CheckpointValidationError("checkpoint size does not match its receipt")
    digest = _sha256_file(checkpoint_path)
    if digest != payload.get("checkpoint_sha256"):
        raise CheckpointValidationError("checkpoint hash does not match its receipt")
    safe_payload: dict[str, Any] = {
        "schema_version": payload["schema_version"],
        "checkpoint_id": payload["checkpoint_id"],
        "task_id": payload["task_id"],
        "round_id": payload["round_id"],
        "contract_sha256": payload["contract_sha256"],
        "checkpoint_sha256": digest,
        "size_bytes": size_bytes,
        "created_at": payload["created_at"],
        "path_exported": False,
        "contains_patient_data": False,
    }
    metadata_sha256 = hashlib.sha256(
        json.dumps(safe_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return CheckpointMetadata.model_validate(
        {
            **safe_payload,
            "schema_version": "rarelink-checkpoint-metadata-v1",
            "metadata_sha256": metadata_sha256,
            "verified_at": utc_now(),
        }
    )
