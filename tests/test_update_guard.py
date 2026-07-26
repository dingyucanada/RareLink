from __future__ import annotations

import math

import pytest

from rarelink.security.update_guard import (
    MemoryReplayRegistry,
    ModelUpdateEnvelope,
    UpdateGuardError,
    UpdateGuardPolicy,
    guard_model_update,
)


def policy() -> UpdateGuardPolicy:
    return UpdateGuardPolicy(
        expected_sites=frozenset({"hospital-a", "hospital-b", "hospital-c"}),
        max_l2_norm=5.0,
        minimum_sample_count=2,
        minimum_cosine_similarity=0.25,
    )


def envelope(**overrides: object) -> ModelUpdateEnvelope:
    values = {
        "job_id": "job-001",
        "site_id": "hospital-a",
        "round_number": 2,
        "nonce": "nonce-001",
        "sample_count": 8,
        "tensors": {"encoder.weight": [6.0, 8.0], "head.bias": [0.0]},
    }
    values.update(overrides)
    return ModelUpdateEnvelope(**values)  # type: ignore[arg-type]


def test_guard_clips_update_and_returns_metadata_only_receipt() -> None:
    guarded = guard_model_update(
        envelope(),
        expected_round=2,
        policy=policy(),
        replay_registry=MemoryReplayRegistry(),
        reference_update=[3.0, 4.0, 0.0],
    )

    assert guarded.tensors["encoder.weight"] == (3.0, 4.0)
    assert guarded.receipt["clipped"] is True
    assert guarded.receipt["original_l2_norm"] == 10.0
    assert guarded.receipt["clipped_l2_norm"] == 5.0
    assert guarded.receipt["cosine_similarity"] == 1.0
    assert "tensors" not in guarded.receipt
    assert guarded.receipt["raw_tensors_exported"] is False


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"site_id": "unknown-site"}, "locked federation contract"),
        ({"round_number": 1}, "Late or future-round"),
        ({"sample_count": 1}, "sample count"),
        ({"tensors": {"weight": [math.nan]}}, "NaN or infinity"),
        ({"tensors": {"weight": [math.inf]}}, "NaN or infinity"),
        ({"tensors": {"weight": [0.0, 0.0]}}, "Zero-norm"),
    ],
)
def test_guard_rejects_untrusted_updates(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(UpdateGuardError, match=message):
        guard_model_update(
            envelope(**overrides),
            expected_round=2,
            policy=policy(),
            replay_registry=MemoryReplayRegistry(),
        )


def test_guard_atomically_rejects_replayed_nonce() -> None:
    registry = MemoryReplayRegistry()
    first = envelope()
    guard_model_update(
        first,
        expected_round=2,
        policy=policy(),
        replay_registry=registry,
    )

    with pytest.raises(UpdateGuardError, match="Duplicate"):
        guard_model_update(
            first,
            expected_round=2,
            policy=policy(),
            replay_registry=registry,
        )


def test_guard_rejects_opposing_update_against_reference() -> None:
    with pytest.raises(UpdateGuardError, match="similarity"):
        guard_model_update(
            envelope(tensors={"weight": [-3.0, -4.0, 0.0]}),
            expected_round=2,
            policy=policy(),
            replay_registry=MemoryReplayRegistry(),
            reference_update=[3.0, 4.0, 0.0],
        )


def test_guard_rejects_oversized_update_before_replay_claim() -> None:
    strict_policy = UpdateGuardPolicy(
        expected_sites=frozenset({"hospital-a", "hospital-b"}),
        max_l2_norm=1.0,
        max_parameters=2,
    )
    registry = MemoryReplayRegistry()
    update = envelope(tensors={"weight": [1.0, 2.0, 3.0]})

    with pytest.raises(UpdateGuardError, match="parameter limit"):
        guard_model_update(
            update,
            expected_round=2,
            policy=strict_policy,
            replay_registry=registry,
        )
    accepted = guard_model_update(
        envelope(tensors={"weight": [1.0, 2.0]}),
        expected_round=2,
        policy=strict_policy,
        replay_registry=registry,
    )
    assert accepted.receipt["accepted"] is True
