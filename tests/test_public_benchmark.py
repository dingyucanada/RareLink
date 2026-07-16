import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from rarelink.imaging.public_benchmark import create_msd_manifest, download_archive

nib = pytest.importorskip("nibabel")


def test_msd_manifest_is_disjoint_and_non_iid(tmp_path: Path) -> None:
    source = tmp_path / "Task01_BrainTumour"
    images = source / "imagesTr"
    labels = source / "labelsTr"
    images.mkdir(parents=True)
    labels.mkdir()
    training = []
    for index in range(6):
        case_id = f"BRATS_{index:03d}"
        image_path = images / f"{case_id}.nii.gz"
        label_path = labels / f"{case_id}.nii.gz"
        image = np.zeros((16, 16, 16, 4), dtype=np.float32)
        label = np.zeros((16, 16, 16), dtype=np.uint8)
        label.flat[: index + 1] = 4 if index == 5 else 1
        nib.save(nib.Nifti1Image(image, np.eye(4)), image_path)
        nib.save(nib.Nifti1Image(label, np.eye(4)), label_path)
        training.append(
            {"image": f"./imagesTr/{case_id}.nii.gz", "label": f"./labelsTr/{case_id}.nii.gz"}
        )
    (source / "dataset.json").write_text(json.dumps({"training": training}), encoding="utf-8")

    manifest = create_msd_manifest(
        source_dir=source,
        output_root=tmp_path / "runtime",
        cases_per_site=2,
        hash_selected_files=False,
    )

    assert manifest["contains_patient_data"] is True
    assert manifest["label_mapping"] == {"0": 0, "1": 1, "2": 2, "4": 2}
    assert {case["site_id"] for case in manifest["cases"]} == {"site-a", "site-b", "site-c"}
    assert {case["partition_cohort"] for case in manifest["cases"]} == {
        "low_tumor_burden",
        "mid_tumor_burden",
        "high_tumor_burden",
    }
    assert all(isinstance(case["images"], str) for case in manifest["cases"])


def test_public_archive_download_resumes_range_request(tmp_path: Path) -> None:
    destination = tmp_path / "Task01_BrainTumour.tar"
    partial = destination.with_suffix(".tar.part")
    partial.write_bytes(b"existing-")
    response = MagicMock()
    response.status = 206
    response.read.side_effect = [b"remaining", b""]
    response.__enter__.return_value = response
    response.__exit__.return_value = False

    with patch(
        "rarelink.imaging.public_benchmark.urllib.request.urlopen", return_value=response
    ) as opened:
        result = download_archive("https://example.test/task.tar", destination)

    assert result.read_bytes() == b"existing-remaining"
    assert opened.call_args.args[0].headers["Range"] == "bytes=9-"
