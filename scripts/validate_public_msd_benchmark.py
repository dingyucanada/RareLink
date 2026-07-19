"""Validate a locally prepared MSD Task01 cohort without exporting patient images.

This is an intake and geometry verification step, not a clinical performance
experiment. The emitted receipt contains aggregate technical facts only: no
case IDs, paths, voxel arrays, image hashes, or raw labels are written to the
evidence directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rarelink.imaging.public_benchmark import MSD_TASK01_LABEL_MAPPING  # noqa: E402


def _resolve(manifest_path: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (manifest_path.parent / path).resolve()


def validate_manifest(manifest_path: Path) -> dict[str, Any]:
    try:
        import nibabel as nib
    except ImportError as exc:  # pragma: no cover - dependency guard for CLI use
        raise RuntimeError("Install nibabel to validate a public NIfTI benchmark") from exc

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != "msd-task01-brain-tumour-v1":
        raise ValueError("Expected the RareLink MSD Task01 manifest")
    if (
        manifest.get("contains_patient_data") is not True
        or manifest.get("public_benchmark") is not True
    ):
        raise ValueError("Manifest must explicitly identify public patient imaging data")
    if manifest.get("clinical_use_prohibited") is not True:
        raise ValueError("Manifest must keep the public benchmark out of clinical use")
    if manifest.get("label_mapping") != MSD_TASK01_LABEL_MAPPING:
        raise ValueError("Unexpected Task01 label mapping")

    cases = manifest.get("cases", [])
    sites = {str(item.get("site_id")) for item in cases}
    if len(cases) < 6 or sites != {"site-a", "site-b", "site-c"}:
        raise ValueError("Need at least two cases in each of the three simulated sites")

    image_shapes: Counter[tuple[int, ...]] = Counter()
    label_shapes: Counter[tuple[int, ...]] = Counter()
    modality_counts: Counter[int] = Counter()
    spacing_values: list[tuple[float, float, float]] = []
    for case in cases:
        image_path = _resolve(manifest_path, str(case["images"]))
        label_path = _resolve(manifest_path, str(case["label"]))
        if not image_path.is_file() or not label_path.is_file():
            raise FileNotFoundError("A selected public benchmark image or label is missing")
        image = nib.load(str(image_path))
        label = nib.load(str(label_path))
        image_shape = tuple(int(value) for value in image.shape)
        label_shape = tuple(int(value) for value in label.shape)
        if len(image_shape) != 4 or image_shape[-1] != 4:
            raise ValueError("MSD Task01 images must expose four registered MRI modalities")
        if image_shape[:3] != label_shape:
            raise ValueError("Public image and segmentation geometry do not match")
        image_shapes[image_shape] += 1
        label_shapes[label_shape] += 1
        modality_counts[image_shape[-1]] += 1
        spacing_values.append(
            tuple(round(float(value), 6) for value in image.header.get_zooms()[:3])
        )

    return {
        "schema_version": "rarelink-public-msd-intake-validation-v1",
        "validated_at_utc": datetime.now(UTC).isoformat(),
        "dataset_id": manifest["dataset_id"],
        "public_benchmark_verified": True,
        "training_executed": False,
        "case_count": len(cases),
        "site_count": len(sites),
        "modalities": manifest["modalities"],
        "registered_modalities_per_case": sorted(modality_counts),
        "image_shape_variants": {
            "×".join(map(str, key)): value for key, value in image_shapes.items()
        },
        "label_shape_variants": {
            "×".join(map(str, key)): value for key, value in label_shapes.items()
        },
        "spacing_variants": len(set(spacing_values)),
        "source": {
            "name": manifest.get("source", {}).get("name"),
            "url": manifest.get("source", {}).get("url"),
            "archive_md5_verified": bool(manifest.get("source", {}).get("archive_md5")),
            "archive_sha256_recorded": bool(manifest.get("source", {}).get("archive_sha256")),
        },
        "data_egress": {
            "raw_images_in_evidence": False,
            "raw_labels_in_evidence": False,
            "case_ids_in_evidence": False,
            "file_paths_in_evidence": False,
        },
        "claim_boundary": (
            "Public NIfTI intake and geometry validation only; this receipt does not report "
            "clinical performance, federated training performance, or a rare-disease cohort result."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a prepared public MSD Task01 cohort")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--evidence-path",
        type=Path,
        default=Path("artifacts/public-benchmark/msd-task01-validation.json"),
    )
    args = parser.parse_args()
    result = validate_manifest(args.manifest)
    args.evidence_path.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
