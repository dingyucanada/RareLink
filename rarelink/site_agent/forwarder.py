"""Persistent, patient-free heartbeat outbox with bounded exponential backoff."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ENVELOPE_FIELDS = {
    "schema_version",
    "site_id",
    "timestamp",
    "heartbeat_id",
    "payload",
    "payload_sha256",
    "algorithm",
    "key_id",
    "signature",
}
CENTRAL_HEARTBEAT_FIELDS = {
    "heartbeat_id",
    "agent_version",
    "status",
    "certificate_status",
    "data_ready",
    "gpu_ready",
    "monai_ready",
    "nvflare_ready",
    "current_job_id",
    "current_round",
    "total_rounds",
    "free_memory_percent",
    "free_disk_percent",
    "receipt_sha256",
    "captured_at",
    "contains_patient_data",
}


@dataclass(frozen=True, slots=True)
class BackoffPolicy:
    base_seconds: float = 5
    maximum_seconds: float = 300
    maximum_envelope_age_seconds: float = 240

    def __post_init__(self) -> None:
        if self.base_seconds <= 0 or self.maximum_seconds < self.base_seconds:
            raise ValueError("backoff bounds are invalid")
        if self.maximum_envelope_age_seconds <= self.base_seconds:
            raise ValueError("maximum envelope age must exceed the base backoff")

    def delay(self, consecutive_failures: int) -> float:
        if consecutive_failures < 1:
            return 0
        exponent = min(consecutive_failures - 1, 30)
        return min(self.maximum_seconds, self.base_seconds * (2**exponent))


@dataclass(frozen=True, slots=True)
class ForwarderState:
    pending_envelope: dict[str, Any] | None
    consecutive_failures: int
    next_attempt_at: float
    last_accepted_heartbeat_id: str | None


def validate_patient_free_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Allow-list fields before persistence; do not store arbitrary API content."""
    if not isinstance(envelope, dict) or set(envelope) != ENVELOPE_FIELDS:
        raise ValueError("Heartbeat envelope fields do not match the reviewed schema")
    payload = envelope.get("payload")
    if not isinstance(payload, dict) or set(payload) != CENTRAL_HEARTBEAT_FIELDS:
        raise ValueError("Heartbeat payload fields do not match the reviewed schema")
    heartbeat_id = envelope.get("heartbeat_id")
    if (
        not isinstance(heartbeat_id, str)
        or payload.get("heartbeat_id") != heartbeat_id
        or payload.get("contains_patient_data") is not False
    ):
        raise ValueError("Heartbeat must be patient-free and use one consistent ID")
    # A JSON round-trip creates an owned primitive-only copy and rejects values
    # that could invoke custom serialization later.
    encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise ValueError("Heartbeat envelope is invalid")
    return decoded


class HeartbeatOutbox:
    """One-record SQLite outbox; it never stores API tokens or HMAC keys."""

    def __init__(self, path: Path, policy: BackoffPolicy | None = None) -> None:
        if path.is_symlink():
            raise ValueError("Heartbeat outbox database must not be a symbolic link")
        self.path = path
        self.policy = policy or BackoffPolicy()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS heartbeat_outbox (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    pending_json TEXT,
                    consecutive_failures INTEGER NOT NULL,
                    next_attempt_at REAL NOT NULL,
                    last_accepted_heartbeat_id TEXT
                )
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO heartbeat_outbox (
                    singleton, pending_json, consecutive_failures,
                    next_attempt_at, last_accepted_heartbeat_id
                ) VALUES (1, NULL, 0, 0, NULL)
                """
            )
        os.chmod(self.path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def state(self) -> ForwarderState:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT pending_json, consecutive_failures, next_attempt_at,
                       last_accepted_heartbeat_id
                FROM heartbeat_outbox WHERE singleton = 1
                """
            ).fetchone()
        if row is None:
            raise RuntimeError("Heartbeat outbox state is unavailable")
        pending = json.loads(row[0]) if row[0] else None
        return ForwarderState(
            pending_envelope=pending,
            consecutive_failures=int(row[1]),
            next_attempt_at=float(row[2]),
            last_accepted_heartbeat_id=row[3],
        )

    def enqueue(self, envelope: dict[str, Any]) -> dict[str, Any] | None:
        safe = validate_patient_free_envelope(envelope)
        heartbeat_id = safe["heartbeat_id"]
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT pending_json, last_accepted_heartbeat_id
                FROM heartbeat_outbox WHERE singleton = 1
                """
            ).fetchone()
            if row is None:
                raise RuntimeError("Heartbeat outbox state is unavailable")
            if row[0]:
                pending = json.loads(row[0])
                return pending
            if row[1] == heartbeat_id:
                return None
            connection.execute(
                """
                UPDATE heartbeat_outbox
                SET pending_json = ?, next_attempt_at = 0
                WHERE singleton = 1
                """,
                (json.dumps(safe, ensure_ascii=False, separators=(",", ":")),),
            )
        return safe

    def record_failure(self, now: float) -> float:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT consecutive_failures FROM heartbeat_outbox WHERE singleton = 1"
            ).fetchone()
            if row is None:
                raise RuntimeError("Heartbeat outbox state is unavailable")
            failures = int(row[0]) + 1
            delay = self.policy.delay(failures)
            connection.execute(
                """
                UPDATE heartbeat_outbox
                SET consecutive_failures = ?, next_attempt_at = ?
                WHERE singleton = 1
                """,
                (failures, now + delay),
            )
        return delay

    def record_accepted(self, heartbeat_id: str) -> None:
        state = self.state()
        pending = state.pending_envelope
        if pending is None or pending.get("heartbeat_id") != heartbeat_id:
            raise ValueError("Accepted heartbeat does not match the pending outbox record")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE heartbeat_outbox
                SET pending_json = NULL, consecutive_failures = 0,
                    next_attempt_at = 0, last_accepted_heartbeat_id = ?
                WHERE singleton = 1
                """,
                (heartbeat_id,),
            )

    def discard_stale(self, heartbeat_id: str) -> None:
        """Drop an unverifiable stale envelope without claiming it was accepted."""
        state = self.state()
        pending = state.pending_envelope
        if pending is None or pending.get("heartbeat_id") != heartbeat_id:
            raise ValueError("Stale heartbeat does not match the pending outbox record")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE heartbeat_outbox
                SET pending_json = NULL, consecutive_failures = 0,
                    next_attempt_at = 0
                WHERE singleton = 1
                """
            )
