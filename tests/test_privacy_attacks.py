from __future__ import annotations

import json

import numpy as np
import pytest

from rarelink.security import privacy_attacks
from rarelink.security.privacy_attacks import (
    PrivacyAttackAssessmentError,
    assess_membership_inference,
    assess_model_inversion,
)

MODEL_SHA = "a" * 64
MEMBER_SHA = "b" * 64
NONMEMBER_SHA = "c" * 64


class SequencedMembershipAttack:
    def __init__(self, _classifier: object) -> None:
        self.calls = 0

    def infer(self, _x: np.ndarray, _y: np.ndarray) -> np.ndarray:
        self.calls += 1
        return np.array([1, 1]) if self.calls == 1 else np.array([0, 1])


class FakeClassifier:
    def predict(self, _x: np.ndarray) -> np.ndarray:
        return np.array([[1.0, 0.0], [0.0, 1.0]])


class FixedInversionAttack:
    def __init__(self, reconstructed: np.ndarray) -> None:
        self.reconstructed = reconstructed

    def infer(self, *, x: None, y: np.ndarray) -> np.ndarray:
        assert x is None
        assert y.shape == (2, 2)
        return self.reconstructed


@pytest.fixture(autouse=True)
def art_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(privacy_attacks, "_tool_version", lambda: "1.20.1-test")


def test_membership_inference_emits_only_aggregate_receipt() -> None:
    receipt = assess_membership_inference(
        object(),
        member_x=np.array([[1.0], [2.0]]),
        member_y=np.array([0, 1]),
        nonmember_x=np.array([[3.0], [4.0]]),
        nonmember_y=np.array([0, 1]),
        member_dataset_sha256=MEMBER_SHA,
        nonmember_dataset_sha256=NONMEMBER_SHA,
        model_sha256=MODEL_SHA,
        max_attack_accuracy=0.8,
        max_attack_advantage=0.6,
        attack_factory=SequencedMembershipAttack,
    )

    assert receipt["passed"] is True
    assert receipt["metrics"]["attack_accuracy"] == 0.75
    assert receipt["metrics"]["attack_advantage"] == 0.5
    assert receipt["sample_predictions_exported"] is False
    serialized = json.dumps(receipt)
    assert "member_x" not in serialized
    assert "nonmember_x" not in serialized


def test_membership_inference_rejects_non_independent_fingerprints() -> None:
    with pytest.raises(PrivacyAttackAssessmentError, match="independently"):
        assess_membership_inference(
            object(),
            member_x=np.array([[1.0], [2.0]]),
            member_y=np.array([0, 1]),
            nonmember_x=np.array([[3.0], [4.0]]),
            nonmember_y=np.array([0, 1]),
            member_dataset_sha256=MEMBER_SHA,
            nonmember_dataset_sha256=MEMBER_SHA,
            model_sha256=MODEL_SHA,
            attack_factory=SequencedMembershipAttack,
        )


def test_model_inversion_discards_reconstructions_and_fails_policy() -> None:
    references = np.array([[0.0, 1.0], [1.0, 0.0]])
    receipt = assess_model_inversion(
        FakeClassifier(),
        target_labels=np.array([[1, 0], [0, 1]]),
        reference_samples=references,
        model_sha256=MODEL_SHA,
        reference_dataset_sha256=MEMBER_SHA,
        maximum_attack_success_rate=0.5,
        minimum_reference_similarity=0.8,
        attack_factory=lambda _classifier: FixedInversionAttack(references.copy()),
    )

    assert receipt["passed"] is False
    assert receipt["metrics"]["attack_success_rate"] == 1.0
    assert receipt["reconstructed_samples_exported"] is False
    assert "reconstructions" not in receipt
    assert "[[0.0, 1.0]" not in json.dumps(receipt)


def test_model_inversion_rejects_unexpected_reconstruction_shape() -> None:
    with pytest.raises(PrivacyAttackAssessmentError, match="reference shape"):
        assess_model_inversion(
            FakeClassifier(),
            target_labels=np.array([[1, 0], [0, 1]]),
            reference_samples=np.array([[0.0, 1.0], [1.0, 0.0]]),
            model_sha256=MODEL_SHA,
            reference_dataset_sha256=MEMBER_SHA,
            attack_factory=lambda _classifier: FixedInversionAttack(np.zeros((2, 3))),
        )
