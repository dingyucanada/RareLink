"""Fail-closed validation for federated model updates.

The control plane only persists the public receipt returned by this module. Raw
model tensors stay inside the aggregation process and are never serialized into
API responses, logs, or the RareLink database.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$")


class UpdateGuardError(ValueError):
    """A model update violated the locked federation policy."""


class ReplayRegistry(Protocol):
    """Atomic replay protection supplied by the production persistence layer."""

    def claim(self, replay_key: str) -> bool:
        """Return true exactly once for a replay key."""


class MemoryReplayRegistry:
    """Deterministic test/development registry; production uses a durable adapter."""

    def __init__(self) -> None:
        self._claimed: set[str] = set()

    def claim(self, replay_key: str) -> bool:
        if replay_key in self._claimed:
            return False
        self._claimed.add(replay_key)
        return True


@dataclass(frozen=True)
class UpdateGuardPolicy:
    expected_sites: frozenset[str]
    max_l2_norm: float
    max_parameters: int = 5_000_000
    minimum_sample_count: int = 1
    minimum_cosine_similarity: float = -1.0

    def validate(self) -> None:
        if len(self.expected_sites) < 2:
            raise UpdateGuardError("At least two expected sites are required")
        if not all(SAFE_ID_RE.fullmatch(site_id) for site_id in self.expected_sites):
            raise UpdateGuardError("Expected site identifiers are invalid")
        if not math.isfinite(self.max_l2_norm) or self.max_l2_norm <= 0:
            raise UpdateGuardError("max_l2_norm must be finite and positive")
        if self.max_parameters < 1:
            raise UpdateGuardError("max_parameters must be positive")
        if self.minimum_sample_count < 1:
            raise UpdateGuardError("minimum_sample_count must be positive")
        if not -1.0 <= self.minimum_cosine_similarity <= 1.0:
            raise UpdateGuardError("minimum_cosine_similarity must be in [-1, 1]")


@dataclass(frozen=True)
class ModelUpdateEnvelope:
    job_id: str
    site_id: str
    round_number: int
    nonce: str
    sample_count: int
    tensors: Mapping[str, Sequence[float]]


@dataclass(frozen=True)
class GuardedModelUpdate:
    """Internal aggregation value plus a safe, metadata-only receipt."""

    tensors: dict[str, tuple[float, ...]]
    receipt: dict[str, object]


def _validate_identifier(value: str, label: str) -> None:
    if not SAFE_ID_RE.fullmatch(value):
        raise UpdateGuardError(f"{label} is invalid")


def _flatten_tensors(
    tensors: Mapping[str, Sequence[float]],
    max_parameters: int,
) -> tuple[list[float], list[tuple[str, int]]]:
    if not tensors:
        raise UpdateGuardError("Model update contains no tensors")
    values: list[float] = []
    shape: list[tuple[str, int]] = []
    for name in sorted(tensors):
        _validate_identifier(name, "Tensor name")
        tensor = tensors[name]
        if not tensor:
            raise UpdateGuardError("Model update contains an empty tensor")
        shape.append((name, len(tensor)))
        for raw_value in tensor:
            value = float(raw_value)
            if not math.isfinite(value):
                raise UpdateGuardError("Model update contains NaN or infinity")
            values.append(value)
            if len(values) > max_parameters:
                raise UpdateGuardError("Model update exceeds the parameter limit")
    return values, shape


def _cosine_similarity(values: Sequence[float], reference: Sequence[float]) -> float:
    if len(values) != len(reference):
        raise UpdateGuardError("Reference update shape does not match")
    if not all(math.isfinite(float(value)) for value in reference):
        raise UpdateGuardError("Reference update contains NaN or infinity")
    dot = sum(value * float(other) for value, other in zip(values, reference, strict=True))
    norm = math.sqrt(sum(value * value for value in values))
    reference_norm = math.sqrt(sum(float(value) ** 2 for value in reference))
    if norm == 0 or reference_norm == 0:
        raise UpdateGuardError("Zero-norm updates cannot be similarity checked")
    return dot / (norm * reference_norm)


def guard_model_update(
    envelope: ModelUpdateEnvelope,
    *,
    expected_round: int,
    policy: UpdateGuardPolicy,
    replay_registry: ReplayRegistry,
    reference_update: Sequence[float] | None = None,
) -> GuardedModelUpdate:
    """Validate, clip, and claim a client update before aggregation.

    Replay protection is claimed only after every deterministic validation has
    passed. A production registry must implement ``claim`` atomically.
    """

    policy.validate()
    _validate_identifier(envelope.job_id, "Job identifier")
    _validate_identifier(envelope.site_id, "Site identifier")
    _validate_identifier(envelope.nonce, "Update nonce")
    if envelope.site_id not in policy.expected_sites:
        raise UpdateGuardError("Site is not part of the locked federation contract")
    if envelope.round_number != expected_round:
        raise UpdateGuardError("Late or future-round model update rejected")
    if envelope.sample_count < policy.minimum_sample_count:
        raise UpdateGuardError("Model update sample count is below policy")

    values, tensor_shape = _flatten_tensors(envelope.tensors, policy.max_parameters)
    original_norm = math.sqrt(sum(value * value for value in values))
    if original_norm == 0:
        raise UpdateGuardError("Zero-norm model update rejected")

    cosine_similarity: float | None = None
    if reference_update is not None:
        cosine_similarity = _cosine_similarity(values, reference_update)
        if cosine_similarity < policy.minimum_cosine_similarity:
            raise UpdateGuardError("Model update failed the anomaly similarity threshold")

    clip_factor = min(1.0, policy.max_l2_norm / original_norm)
    clipped: dict[str, tuple[float, ...]] = {
        name: tuple(float(value) * clip_factor for value in envelope.tensors[name])
        for name, _length in tensor_shape
    }
    canonical_shape = json.dumps(tensor_shape, separators=(",", ":"), ensure_ascii=True)
    shape_sha256 = hashlib.sha256(canonical_shape.encode("utf-8")).hexdigest()
    replay_key = hashlib.sha256(
        (
            f"{envelope.job_id}\x00{envelope.site_id}\x00"
            f"{envelope.round_number}\x00{envelope.nonce}"
        ).encode()
    ).hexdigest()
    if not replay_registry.claim(replay_key):
        raise UpdateGuardError("Duplicate model update rejected")

    clipped_norm = original_norm * clip_factor
    receipt: dict[str, object] = {
        "schema_version": "rarelink-update-guard-v1",
        "job_id": envelope.job_id,
        "site_id": envelope.site_id,
        "round_number": envelope.round_number,
        "sample_count": envelope.sample_count,
        "parameter_count": len(values),
        "tensor_shape_sha256": shape_sha256,
        "original_l2_norm": round(original_norm, 8),
        "clipped_l2_norm": round(clipped_norm, 8),
        "clipped": not hmac.compare_digest(str(clip_factor), "1.0"),
        "cosine_similarity": (
            round(cosine_similarity, 8) if cosine_similarity is not None else None
        ),
        "replay_key_sha256": replay_key,
        "accepted": True,
        "raw_tensors_exported": False,
        "patient_data_exported": False,
    }
    return GuardedModelUpdate(tensors=clipped, receipt=receipt)
