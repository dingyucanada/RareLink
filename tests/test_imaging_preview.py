from pathlib import Path

import pytest

from rarelink.imaging.preview import build_synthetic_imaging_preview
from rarelink.imaging.synthetic import generate_synthetic_dataset

pytest.importorskip("nibabel")


def test_build_synthetic_imaging_preview_has_four_modalities_and_no_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "synthetic"
    generate_synthetic_dataset(root, cases_per_site=2, shape=(16, 16, 16))

    preview = build_synthetic_imaging_preview(root / "manifest.json", "site-b")

    assert preview["synthetic"] is True
    assert preview["sent_to_llm"] is False
    assert len(preview["modalities"]) == 4
    assert preview["shape"] == [16, 16]
    assert "images" not in preview
    assert "label" not in preview


def test_preview_rejects_patient_data_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"contains_patient_data": true}', encoding="utf-8")

    with pytest.raises(PermissionError, match="synthetic"):
        build_synthetic_imaging_preview(manifest, "site-a")
