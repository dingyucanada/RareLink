"""Directly validate a small public structural-MRI NIfTI pair on the Spark node.

This is intentionally labelled as an intake/geometry validation, not a tumour
benchmark or clinical experiment. It provides an external, non-synthetic NIfTI
check while the much larger MSD Task01 archive remains a resumable follow-up.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BASE_URL = "https://github.com/Project-MONAI/MONAI-extra-test-data/releases/download/0.8.1"
ASSETS = {
    "image": "MNI152_T1_2mm.nii.gz",
    "label": "MNI152_T1_2mm_strucseg.nii.gz",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path) -> None:
    if destination.exists():
        return
    temporary = destination.with_suffix(destination.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    temporary.replace(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a public MNI152 NIfTI image/label pair")
    parser.add_argument("--data-root", type=Path, default=Path("data/raw/public-mni152"))
    parser.add_argument(
        "--evidence-path",
        type=Path,
        default=Path("artifacts/public-benchmark/latest-intake-validation.json"),
    )
    args = parser.parse_args()
    try:
        import nibabel as nib
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install nibabel before validating NIfTI") from exc

    args.data_root.mkdir(parents=True, exist_ok=True)
    paths = {key: args.data_root / name for key, name in ASSETS.items()}
    for key, path in paths.items():
        download(f"{BASE_URL}/{ASSETS[key]}", path)
    image, label = nib.load(str(paths["image"])), nib.load(str(paths["label"]))
    if image.shape != label.shape:
        raise ValueError("Public image and structural label geometry do not match")
    evidence = {
        "schema_version": "rarelink-public-mri-intake-validation-v1",
        "validated_at_utc": datetime.now(UTC).isoformat(),
        "dataset_id": "mni152-public-structural-mri-validation",
        "public_benchmark_verified": False,
        "public_mri_intake_verified": True,
        "training_executed": False,
        "case_count": 1,
        "site_count": 0,
        "modalities": ["T1w"],
        "image_shape": list(image.shape),
        "spacing": [round(float(value), 6) for value in image.header.get_zooms()[:3]],
        "source": {
            "name": "Project MONAI public MNI152 structural-MRI test asset",
            "url": BASE_URL,
            "archive_md5_verified": False,
            "archive_sha256_recorded": True,
            "asset_sha256": {key: sha256(path) for key, path in paths.items()},
        },
        "data_egress": {"raw_images_in_evidence": False, "raw_labels_in_evidence": False},
        "claim_boundary": (
            "One public structural-MRI image/label pair passed local NIfTI intake and geometry "
            "checks. This is not MSD Task01, federated training, tumour performance, or clinical "
            "validation."
        ),
    }
    args.evidence_path.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
