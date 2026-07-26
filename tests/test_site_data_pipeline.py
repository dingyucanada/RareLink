from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from rarelink.site_data import (
    DatasetSplitError,
    DatasetValidationError,
    MonaiPreprocessingPlan,
    deterministic_dataset_split,
    materialize_monai_preprocessing_cache,
    validate_site_dataset,
    verify_site_dataset_receipt,
)

nib = pytest.importorskip("nibabel")
monai = pytest.importorskip("monai")


def local_dataset(tmp_path: Path, *, case_count: int = 3) -> Path:
    root = tmp_path / "hospital-data"
    root.mkdir(parents=True)
    cases = []
    affine = np.diag([1.0, 1.0, 1.0, 1.0])
    for case_index in range(case_count):
        images = []
        for modality_index in range(4):
            path = root / f"private-{case_index}-modality-{modality_index}.nii.gz"
            image = np.zeros((6, 7, 8), dtype=np.float32) + modality_index
            image[1:5, 1:6, 1:7] += case_index + 1
            nib.save(nib.Nifti1Image(image, affine), path)
            images.append(path.name)
        label_path = root / f"private-{case_index}-label.nii.gz"
        label = np.zeros((6, 7, 8), dtype=np.uint8)
        label[2:4, 2:4, 2:4] = 1 + (case_index % 2)
        nib.save(nib.Nifti1Image(label, affine), label_path)
        cases.append(
            {
                "case_id": f"opaque-local-case-{case_index:03d}",
                "site_id": "hospital-a",
                "images": images,
                "label": label_path.name,
            }
        )
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "rarelink-site-manifest-v1",
                "modalities": ["FLAIR", "T1w", "T1wCE", "T2w"],
                "allowed_label_values": [0, 1, 2],
                "cases": cases,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_seeded_split_is_order_independent_and_receipt_has_no_case_ids() -> None:
    cases = [
        {"case_id": f"opaque-case-{index:03d}", "site_id": "hospital-a"}
        for index in range(10)
    ]

    first = deterministic_dataset_split(cases, seed=2026, validation_fraction=0.2)
    reordered = deterministic_dataset_split(
        list(reversed(cases)),
        seed=2026,
        validation_fraction=0.2,
    )

    assert {case["case_id"] for case in first.train_cases} == {
        case["case_id"] for case in reordered.train_cases
    }
    assert {case["case_id"] for case in first.validation_cases} == {
        case["case_id"] for case in reordered.validation_cases
    }
    assert first.receipt == reordered.receipt
    assert first.receipt["train_case_count"] == 8
    assert first.receipt["validation_case_count"] == 2
    serialized = json.dumps(first.receipt)
    assert "opaque-case" not in serialized
    assert first.receipt["case_assignments_exported"] is False


def test_seeded_split_rejects_duplicate_or_nonopaque_identifiers() -> None:
    with pytest.raises(DatasetSplitError, match="unique"):
        deterministic_dataset_split(
            [{"case_id": "opaque-case"}, {"case_id": "opaque-case"}],
            seed=2026,
        )
    with pytest.raises(DatasetSplitError, match="opaque"):
        deterministic_dataset_split(
            [{"case_id": "patient name"}, {"case_id": "opaque-case"}],
            seed=2026,
        )


def test_dataset_proof_binds_seeded_split_without_exporting_assignments(
    tmp_path: Path,
) -> None:
    manifest = local_dataset(tmp_path, case_count=5)

    receipt = validate_site_dataset(
        manifest,
        site_id="hospital-a",
        split_seed=73,
        validation_fraction=0.4,
    )

    assert receipt["split"]["seed"] == 73
    assert receipt["split"]["train_case_count"] == 3
    assert receipt["split"]["validation_case_count"] == 2
    serialized = json.dumps(receipt)
    assert "opaque-local-case" not in serialized
    assert "private-" not in serialized

    receipt_path = tmp_path / "dataset-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    verify_site_dataset_receipt(
        receipt_path,
        manifest,
        site_id="hospital-a",
    )
    receipt["split"]["seed"] = 74
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(DatasetValidationError, match="stale|mismatched|split"):
        verify_site_dataset_receipt(
            receipt_path,
            manifest,
            site_id="hospital-a",
        )


def test_monai_persistent_cache_uses_content_bound_plan_and_safe_receipt(
    tmp_path: Path,
) -> None:
    manifest = local_dataset(tmp_path, case_count=3)
    dataset_receipt = validate_site_dataset(
        manifest,
        site_id="hospital-a",
        split_seed=91,
    )
    receipt_path = tmp_path / "dataset-receipt.json"
    receipt_path.write_text(json.dumps(dataset_receipt), encoding="utf-8")
    plan = MonaiPreprocessingPlan(
        monai_version=str(monai.__version__),
        target_spacing=(1.0, 1.0, 1.0),
        spatial_divisor=4,
    )

    cache_receipt = materialize_monai_preprocessing_cache(
        manifest,
        receipt_path,
        site_id="hospital-a",
        cache_root=tmp_path / "monai-cache",
        plan=plan,
    )

    assert cache_receipt["passed"] is True
    assert cache_receipt["cached_item_count"] == 3
    assert cache_receipt["cache_file_count"] >= 3
    assert cache_receipt["preprocessing_plan_sha256"] == plan.plan_sha256
    assert cache_receipt["preprocessing_plan"]["random_transforms"] is False
    assert cache_receipt["split"] == dataset_receipt["split"]
    assert cache_receipt["cache_is_hospital_local"] is True
    serialized = json.dumps(cache_receipt)
    assert "opaque-local-case" not in serialized
    assert "private-" not in serialized
    assert str(tmp_path) not in serialized
