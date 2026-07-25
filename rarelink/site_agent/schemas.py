"""Wire and persistence models containing only non-patient task metadata."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")


def utc_now() -> datetime:
    return datetime.now(UTC)


class TaskState(StrEnum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    RECOVERING = "RECOVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    status: str
    details: dict[str, Any] = Field(default_factory=dict)


class HealthSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready: bool
    checked_at: datetime
    checks: dict[str, CheckResult]
    contains_patient_data: bool = False
    contains_local_paths: bool = False


class TaskActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    round_id: int = Field(ge=1, le=100_000)
    total_rounds: int = Field(default=0, ge=0, le=100_000)
    contract_sha256: str

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: str) -> str:
        if not SAFE_ID.fullmatch(value):
            raise ValueError("task_id must be a safe opaque identifier")
        return value

    @field_validator("contract_sha256")
    @classmethod
    def validate_contract_hash(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not SHA256.fullmatch(normalized):
            raise ValueError("contract_sha256 must be a lower-case SHA-256 digest")
        return normalized

    @model_validator(mode="after")
    def validate_round_range(self) -> TaskActionRequest:
        if self.total_rounds and self.round_id > self.total_rounds:
            raise ValueError("round_id cannot exceed total_rounds")
        return self


class SignedReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rarelink-site-receipt-v1"
    receipt_id: str
    event: str
    site_id: str
    task_id: str
    round_id: int
    total_rounds: int = 0
    contract_sha256: str
    state: TaskState
    revision: int
    issued_at: datetime
    payload_sha256: str
    algorithm: str = "HMAC-SHA256"
    key_id: str
    signature: str
    contains_patient_data: bool = False
    contains_local_paths: bool = False
    contains_secret: bool = False


class TaskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    round_id: int
    total_rounds: int = 0
    contract_sha256: str
    state: TaskState
    revision: int = 1
    executor_ref: str | None = None
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime
    receipt: SignedReceipt


class TaskActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record: TaskRecord
    idempotent_replay: bool


class HeartbeatEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rarelink-site-heartbeat-v1"
    site_id: str
    timestamp: int
    heartbeat_id: str
    payload: dict[str, Any]
    payload_sha256: str
    algorithm: str = "HMAC-SHA256"
    key_id: str
    signature: str
