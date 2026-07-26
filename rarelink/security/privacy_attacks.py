"""Local-only privacy attack assessments backed by IBM/LF AI ART.

The functions in this module intentionally accept in-memory arrays and return
aggregate receipts. They do not accept output paths and never return sample
predictions or reconstructed images.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import math
import re
from collections.abc import Callable
from typing import Any

SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PrivacyAttackAssessmentError(ValueError):
    """The attack inputs or result violated the locked assessment contract."""


def _tool_version() -> str:
    try:
        return importlib.metadata.version("adversarial-robustness-toolbox")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError(
            "Install RareLink's security extra to run ART privacy attacks"
        ) from exc


def _validate_fingerprint(value: str, label: str) -> None:
    if not SHA256.fullmatch(value):
        raise PrivacyAttackAssessmentError(f"{label} must be a lowercase SHA-256 digest")


def _safe_divide(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _membership_metrics(
    member_predictions: Any,
    nonmember_predictions: Any,
) -> dict[str, float | int]:
    import numpy as np

    members = np.asarray(member_predictions).reshape(-1)
    nonmembers = np.asarray(nonmember_predictions).reshape(-1)
    if members.size < 2 or nonmembers.size < 2:
        raise PrivacyAttackAssessmentError(
            "Membership assessment requires at least two members and two non-members"
        )
    if not np.isin(members, [0, 1, False, True]).all() or not np.isin(
        nonmembers, [0, 1, False, True]
    ).all():
        raise PrivacyAttackAssessmentError("Membership attack returned non-binary decisions")
    true_positive = int(np.count_nonzero(members))
    false_negative = int(members.size - true_positive)
    false_positive = int(np.count_nonzero(nonmembers))
    true_negative = int(nonmembers.size - false_positive)
    total = int(members.size + nonmembers.size)
    accuracy = _safe_divide(true_positive + true_negative, total)
    precision = _safe_divide(true_positive, true_positive + false_positive)
    recall = _safe_divide(true_positive, true_positive + false_negative)
    false_positive_rate = _safe_divide(false_positive, false_positive + true_negative)
    advantage = recall - false_positive_rate
    return {
        "member_count": int(members.size),
        "nonmember_count": int(nonmembers.size),
        "true_positive": true_positive,
        "true_negative": true_negative,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "attack_accuracy": round(accuracy, 8),
        "attack_precision": round(precision, 8),
        "attack_recall": round(recall, 8),
        "false_positive_rate": round(false_positive_rate, 8),
        "attack_advantage": round(advantage, 8),
    }


def assess_membership_inference(
    classifier: Any,
    *,
    member_x: Any,
    member_y: Any,
    nonmember_x: Any,
    nonmember_y: Any,
    member_dataset_sha256: str,
    nonmember_dataset_sha256: str,
    model_sha256: str,
    max_attack_accuracy: float = 0.6,
    max_attack_advantage: float = 0.2,
    attack_factory: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    """Run ART's rule-based black-box membership attack and emit aggregates only."""
    import numpy as np

    for value, label in (
        (member_dataset_sha256, "member_dataset_sha256"),
        (nonmember_dataset_sha256, "nonmember_dataset_sha256"),
        (model_sha256, "model_sha256"),
    ):
        _validate_fingerprint(value, label)
    if member_dataset_sha256 == nonmember_dataset_sha256:
        raise PrivacyAttackAssessmentError(
            "Member and non-member datasets must be independently fingerprinted"
        )
    if not 0.5 <= max_attack_accuracy <= 1.0:
        raise PrivacyAttackAssessmentError("max_attack_accuracy must be in [0.5, 1]")
    if not 0.0 <= max_attack_advantage <= 1.0:
        raise PrivacyAttackAssessmentError("max_attack_advantage must be in [0, 1]")
    if len(member_x) != len(member_y) or len(nonmember_x) != len(nonmember_y):
        raise PrivacyAttackAssessmentError("Attack features and labels must have equal lengths")
    if attack_factory is None:
        try:
            from art.attacks.inference.membership_inference import (
                MembershipInferenceBlackBoxRuleBased,
            )
        except ImportError as exc:
            raise RuntimeError(
                "Install RareLink's security extra to run ART privacy attacks"
            ) from exc
        attack_factory = MembershipInferenceBlackBoxRuleBased
    attack = attack_factory(classifier)
    member_predictions = attack.infer(np.asarray(member_x), np.asarray(member_y))
    nonmember_predictions = attack.infer(np.asarray(nonmember_x), np.asarray(nonmember_y))
    metrics = _membership_metrics(member_predictions, nonmember_predictions)
    passed = (
        float(metrics["attack_accuracy"]) <= max_attack_accuracy
        and float(metrics["attack_advantage"]) <= max_attack_advantage
    )
    contract = {
        "max_attack_accuracy": max_attack_accuracy,
        "max_attack_advantage": max_attack_advantage,
    }
    receipt_material = (
        f"{model_sha256}:{member_dataset_sha256}:{nonmember_dataset_sha256}:"
        f"{metrics['attack_accuracy']}:{metrics['attack_advantage']}:{contract}"
    )
    return {
        "schema_version": "rarelink-art-membership-inference-v1",
        "tool": "adversarial-robustness-toolbox",
        "tool_version": _tool_version(),
        "attack": "MembershipInferenceBlackBoxRuleBased",
        "model_sha256": model_sha256,
        "member_dataset_sha256": member_dataset_sha256,
        "nonmember_dataset_sha256": nonmember_dataset_sha256,
        "metrics": metrics,
        "policy": contract,
        "passed": passed,
        "receipt_sha256": hashlib.sha256(receipt_material.encode()).hexdigest(),
        "sample_predictions_exported": False,
        "raw_inputs_exported": False,
        "case_identifiers_exported": False,
        "claim_boundary": (
            "Engineering attack receipt for the supplied locked model and datasets; "
            "not a clinical privacy guarantee or proof of non-membership."
        ),
    }


def assess_model_inversion(
    classifier: Any,
    *,
    target_labels: Any,
    reference_samples: Any,
    model_sha256: str,
    reference_dataset_sha256: str,
    maximum_attack_success_rate: float = 0.1,
    minimum_reference_similarity: float = 0.8,
    attack_factory: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    """Run ART MIFace locally and discard every reconstruction after aggregation.

    MIFace is a classifier-oriented engineering probe. RareLink does not claim
    that it covers every inversion threat against a 3D segmentation model.
    """
    import numpy as np

    _validate_fingerprint(model_sha256, "model_sha256")
    _validate_fingerprint(reference_dataset_sha256, "reference_dataset_sha256")
    if not 0 <= maximum_attack_success_rate <= 1:
        raise PrivacyAttackAssessmentError("maximum_attack_success_rate must be in [0, 1]")
    if not 0 <= minimum_reference_similarity <= 1:
        raise PrivacyAttackAssessmentError("minimum_reference_similarity must be in [0, 1]")
    references = np.asarray(reference_samples, dtype=np.float64)
    labels = np.asarray(target_labels)
    if references.shape[0] < 2 or references.shape[0] != labels.shape[0]:
        raise PrivacyAttackAssessmentError(
            "Model inversion requires aligned labels and at least two reference samples"
        )
    if not np.isfinite(references).all():
        raise PrivacyAttackAssessmentError("Reference samples contain NaN or infinity")
    if attack_factory is None:
        try:
            from art.attacks.inference.model_inversion import MIFace
        except ImportError as exc:
            raise RuntimeError(
                "Install RareLink's security extra to run ART privacy attacks"
            ) from exc
        attack_factory = lambda estimator: MIFace(  # noqa: E731
            estimator,
            max_iter=2000,
            verbose=False,
        )
    attack = attack_factory(classifier)
    reconstructed_for_model = np.asarray(attack.infer(x=None, y=labels))
    reconstructed = np.asarray(reconstructed_for_model, dtype=np.float64)
    if reconstructed.shape != references.shape or not np.isfinite(reconstructed).all():
        raise PrivacyAttackAssessmentError(
            "Model inversion output does not match the locked reference shape"
        )
    predictions = np.asarray(classifier.predict(reconstructed_for_model))
    predicted_labels = (
        predictions.argmax(axis=1) if predictions.ndim > 1 else predictions.reshape(-1)
    )
    expected_labels = labels.argmax(axis=1) if labels.ndim > 1 else labels.reshape(-1)
    flat_reference = references.reshape(references.shape[0], -1)
    flat_reconstruction = reconstructed.reshape(reconstructed.shape[0], -1)
    dynamic_range = np.ptp(flat_reference, axis=1)
    dynamic_range = np.where(dynamic_range > 0, dynamic_range, 1.0)
    rmse = np.sqrt(np.mean((flat_reference - flat_reconstruction) ** 2, axis=1))
    similarity = 1.0 / (1.0 + rmse / dynamic_range)
    successful = (predicted_labels == expected_labels) & (
        similarity >= minimum_reference_similarity
    )
    attack_success_rate = float(np.mean(successful))
    mean_similarity = float(np.mean(similarity))
    passed = attack_success_rate <= maximum_attack_success_rate
    receipt_material = (
        f"{model_sha256}:{reference_dataset_sha256}:{attack_success_rate}:"
        f"{mean_similarity}:{maximum_attack_success_rate}:{minimum_reference_similarity}"
    )
    if not math.isfinite(attack_success_rate) or not math.isfinite(mean_similarity):
        raise PrivacyAttackAssessmentError("Model inversion metrics are not finite")
    return {
        "schema_version": "rarelink-art-model-inversion-v1",
        "tool": "adversarial-robustness-toolbox",
        "tool_version": _tool_version(),
        "attack": "MIFace",
        "model_sha256": model_sha256,
        "reference_dataset_sha256": reference_dataset_sha256,
        "sample_count": int(references.shape[0]),
        "metrics": {
            "attack_success_rate": round(attack_success_rate, 8),
            "mean_reference_similarity": round(mean_similarity, 8),
        },
        "policy": {
            "maximum_attack_success_rate": maximum_attack_success_rate,
            "minimum_reference_similarity": minimum_reference_similarity,
        },
        "passed": passed,
        "receipt_sha256": hashlib.sha256(receipt_material.encode()).hexdigest(),
        "reconstructed_samples_exported": False,
        "raw_inputs_exported": False,
        "case_identifiers_exported": False,
        "claim_boundary": (
            "Classifier-oriented ART MIFace engineering probe. It does not cover all "
            "gradient, update, or 3D segmentation reconstruction attacks."
        ),
    }
