import json
from pathlib import Path

import numpy as np
import pytest

from scripts.validate_public_msd_benchmark import validate_manifest

nib = pytest.importorskip("nibabel")


def test_public_msd_intake_receipt_is_aggregate_only(tmp_path: Path) -> None:
    dataset = tmp_path / "public"
    dataset.mkdir()
    cases = []
    for index, site in enumerate(("site-a", "site-a", "site-b", "site-b", "site-c", "site-c")):
        image_path = dataset / f"image-{index}.nii.gz"
        label_path = dataset / f"label-{index}.nii.gz"
        nib.save(nib.Nifti1Image(np.zeros((8, 8, 8, 4), dtype=np.float32), np.eye(4)), image_path)
        nib.save(nib.Nifti1Image(np.zeros((8, 8, 8), dtype=np.uint8), np.eye(4)), label_path)
        cases.append(
            {
                "case_id": f"private-{index}",
                "site_id": site,
                "images": image_path.name,
                "label": label_path.name,
            }
        )
    manifest = {
        "dataset_id": "msd-task01-brain-tumour-v1",
        "contains_patient_data": True,
        "public_benchmark": True,
        "clinical_use_prohibited": True,
        "modalities": ["FLAIR", "T1w", "T1wCE", "T2w"],
        "label_mapping": {"0": 0, "1": 1, "2": 2, "3": 2},
        "source": {
            "name": "MSD",
            "url": "https://medicaldecathlon.com/",
            "archive_md5": "x",
            "archive_sha256": "y",
        },
        "cases": cases,
    }
    manifest_path = dataset / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    receipt = validate_manifest(manifest_path)

    assert receipt["public_benchmark_verified"] is True
    assert receipt["case_count"] == 6
    assert receipt["registered_modalities_per_case"] == [4]
    serialized = json.dumps(receipt)
    assert "private-" not in serialized
    assert str(image_path) not in serialized
