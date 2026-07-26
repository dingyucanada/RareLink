"""Run real ART membership-inference and model-inversion engineering probes.

This smoke test uses deterministic synthetic tensors only. It proves the attack
toolchain is executable; it is not privacy evidence for a medical model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np  # noqa: E402
import torch  # noqa: E402
from art.attacks.inference.model_inversion import MIFace  # noqa: E402
from art.estimators.classification import PyTorchClassifier  # noqa: E402
from torch import nn  # noqa: E402

from rarelink.security.privacy_attacks import (  # noqa: E402
    assess_membership_inference,
    assess_model_inversion,
)


def digest_array(value: np.ndarray) -> str:
    digest = hashlib.sha256()
    digest.update(str(value.dtype).encode())
    digest.update(str(value.shape).encode())
    digest.update(value.tobytes(order="C"))
    return digest.hexdigest()


def digest_model(model: nn.Module) -> str:
    digest = hashlib.sha256()
    for name, value in sorted(model.state_dict().items()):
        digest.update(name.encode())
        digest.update(value.detach().cpu().numpy().tobytes(order="C"))
    return digest.hexdigest()


def build_classifier(seed: int) -> tuple[PyTorchClassifier, nn.Module, np.ndarray, np.ndarray]:
    np.random.seed(seed)
    torch.manual_seed(seed)
    generator = np.random.default_rng(seed)
    features = generator.random((80, 1, 2, 2), dtype=np.float32)
    labels = (features.reshape(80, -1).sum(axis=1) > 2.0).astype(np.int64)
    one_hot = np.eye(2, dtype=np.float32)[labels]
    model = nn.Sequential(
        nn.Flatten(),
        nn.Linear(4, 8),
        nn.ReLU(),
        nn.Linear(8, 2),
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=0.04)
    classifier = PyTorchClassifier(
        model=model,
        loss=nn.CrossEntropyLoss(),
        optimizer=optimizer,
        input_shape=(1, 2, 2),
        nb_classes=2,
        clip_values=(0.0, 1.0),
    )
    classifier.fit(features[:48], one_hot[:48], batch_size=8, nb_epochs=30)
    return classifier, model, features, one_hot


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local synthetic ART privacy probes")
    parser.add_argument("--seed", type=int, default=20260726)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/privacy-redteam/art-smoke-summary.json"),
    )
    args = parser.parse_args()
    classifier, model, features, labels = build_classifier(args.seed)
    model_sha256 = digest_model(model)
    member_x, member_y = features[24:48], labels[24:48]
    nonmember_x, nonmember_y = features[48:72], labels[48:72]
    membership = assess_membership_inference(
        classifier,
        member_x=member_x,
        member_y=member_y,
        nonmember_x=nonmember_x,
        nonmember_y=nonmember_y,
        member_dataset_sha256=digest_array(member_x),
        nonmember_dataset_sha256=digest_array(nonmember_x),
        model_sha256=model_sha256,
    )
    class_indices = labels.argmax(axis=1)
    references = np.stack(
        [features[:48][class_indices[:48] == class_id].mean(axis=0) for class_id in range(2)]
    )
    inversion = assess_model_inversion(
        classifier,
        target_labels=np.eye(2, dtype=np.float32),
        reference_samples=references,
        model_sha256=model_sha256,
        reference_dataset_sha256=digest_array(references),
        attack_factory=lambda estimator: MIFace(
            estimator,
            max_iter=50,
            window_length=5,
            threshold=0.9,
            learning_rate=0.1,
            batch_size=1,
            verbose=False,
        ),
    )
    summary = {
        "schema_version": "rarelink-art-privacy-smoke-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "seed": args.seed,
        "synthetic_data_only": True,
        "medical_data_used": False,
        "membership_inference": membership,
        "model_inversion": inversion,
        "raw_inputs_exported": False,
        "sample_predictions_exported": False,
        "reconstructed_samples_exported": False,
        "claim_boundary": (
            "Executable ART toolchain smoke on synthetic tensors. This is not a privacy "
            "assessment of RareLink's medical segmentation model."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
