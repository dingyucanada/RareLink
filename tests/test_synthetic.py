from pathlib import Path

import pytest

from rarelink.imaging.synthetic import generate_synthetic_dataset, sha256_file

nib = pytest.importorskip("nibabel")


def test_generate_synthetic_nifti_manifest(tmp_path: Path) -> None:
    manifest = generate_synthetic_dataset(
        tmp_path / "demo",
        cases_per_site=2,
        shape=(16, 16, 16),
    )

    assert manifest["contains_patient_data"] is False
    assert len(manifest["cases"]) == 6
    first = manifest["cases"][0]
    assert len(first["images"]) == 4
    image_path = tmp_path / "demo" / first["images"][0]
    assert nib.load(image_path).shape == (16, 16, 16)
    assert first["sha256"][first["images"][0]] == sha256_file(image_path)
