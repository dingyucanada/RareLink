import json
import os
from pathlib import Path

import numpy as np
import pytest

from rarelink.site_agent.config import SiteAgentSettings
from rarelink.site_agent.health import _dataset_check
from rarelink.site_data import (
    DatasetValidationError,
    validate_site_dataset,
    verify_site_dataset_receipt,
)

nib = pytest.importorskip("nibabel")


def local_dataset(tmp_path: Path) -> tuple[Path, list[Path]]:
    root = tmp_path / "hospital-data"
    root.mkdir(parents=True)
    cases = []
    files: list[Path] = []
    affine = np.diag([1.0, 1.0, 1.2, 1.0])
    for case_index in range(2):
        images = []
        for modality_index in range(4):
            path = root / f"local-{case_index}-modality-{modality_index}.nii.gz"
            nib.save(
                nib.Nifti1Image(
                    np.zeros((8, 8, 8), dtype=np.float32) + modality_index,
                    affine,
                ),
                path,
            )
            images.append(path.name)
            files.append(path)
        label_path = root / f"local-{case_index}-label.nii.gz"
        label = np.zeros((8, 8, 8), dtype=np.uint8)
        label[2:4, 2:4, 2:4] = case_index + 1
        nib.save(nib.Nifti1Image(label, affine), label_path)
        files.append(label_path)
        cases.append(
            {
                "case_id": f"private-local-case-{case_index}",
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
    return manifest, files


def test_site_dataset_receipt_is_deidentified_and_content_bound(tmp_path: Path) -> None:
    manifest, files = local_dataset(tmp_path)

    receipt = validate_site_dataset(manifest, site_id="hospital-a")

    assert receipt["passed"] is True
    assert receipt["case_count"] == 2
    assert receipt["modalities_per_case"] == 4
    assert receipt["labels"]["observed_values"] == [0, 1, 2]
    assert len(receipt["dataset_fingerprint"]) == 64
    serialized = json.dumps(receipt)
    assert "private-local-case" not in serialized
    assert files[0].name not in serialized
    assert str(manifest.parent) not in serialized


def test_site_dataset_rejects_foreign_site_and_direct_identifiers_before_io(
    tmp_path: Path,
) -> None:
    manifest, _files = local_dataset(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["cases"][1]["site_id"] = "hospital-b"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatasetValidationError, match="local Site ID"):
        validate_site_dataset(manifest, site_id="hospital-a")

    payload["cases"][1]["site_id"] = "hospital-a"
    payload["cases"][0]["patient_name"] = "must-never-enter-a-manifest"
    payload["cases"][0]["images"] = ["missing.nii.gz"] * 4
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DatasetValidationError, match="direct-identifier"):
        validate_site_dataset(manifest, site_id="hospital-a")


def test_site_dataset_rejects_unregistered_geometry_and_invalid_labels(
    tmp_path: Path,
) -> None:
    manifest, files = local_dataset(tmp_path)
    nib.save(
        nib.Nifti1Image(np.zeros((7, 8, 8), dtype=np.float32), np.eye(4)),
        files[0],
    )
    with pytest.raises(DatasetValidationError, match="shapes do not match"):
        validate_site_dataset(manifest, site_id="hospital-a")

    manifest, files = local_dataset(tmp_path / "labels")
    invalid_label = np.full((8, 8, 8), 9, dtype=np.uint8)
    nib.save(nib.Nifti1Image(invalid_label, np.diag([1.0, 1.0, 1.2, 1.0])), files[4])
    with pytest.raises(DatasetValidationError, match="label contract"):
        validate_site_dataset(manifest, site_id="hospital-a")


def test_site_dataset_rejects_path_escape_even_when_target_exists(tmp_path: Path) -> None:
    manifest, _files = local_dataset(tmp_path)
    outside = tmp_path / "outside.nii.gz"
    nib.save(nib.Nifti1Image(np.zeros((8, 8, 8), dtype=np.float32), np.eye(4)), outside)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["cases"][0]["images"][0] = "../outside.nii.gz"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatasetValidationError, match="escapes"):
        validate_site_dataset(manifest, site_id="hospital-a")


def test_site_agent_marks_dataset_receipt_stale_after_local_file_change(
    tmp_path: Path,
) -> None:
    manifest, files = local_dataset(tmp_path)
    receipt = validate_site_dataset(manifest, site_id="hospital-a")
    receipt_path = tmp_path / "dataset-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    settings = SiteAgentSettings(
        _env_file=None,
        site_id="hospital-a",
        dataset_manifest=manifest,
        dataset_root=manifest.parent,
        dataset_receipt=receipt_path,
        artifact_root=tmp_path / "artifacts",
        startup_kit=tmp_path / "startup-kit",
        state_database=tmp_path / "state.sqlite3",
        api_token="site-agent-test-token-000000",
        receipt_hmac_key="site-agent-test-hmac-key-000000000000",
    )

    assert _dataset_check(settings).status == "receipt_verified"
    stat = files[0].stat()
    os.utime(files[0], ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    stale = _dataset_check(settings)
    assert stale.ok is False
    assert stale.status == "receipt_or_dataset_invalid"


def test_training_time_verification_rechecks_content_fingerprint(tmp_path: Path) -> None:
    manifest, _files = local_dataset(tmp_path)
    receipt = validate_site_dataset(manifest, site_id="hospital-a")
    receipt_path = tmp_path / "dataset-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    verified = verify_site_dataset_receipt(
        receipt_path,
        manifest,
        site_id="hospital-a",
        verify_content=True,
    )
    assert verified["dataset_fingerprint"] == receipt["dataset_fingerprint"]

    receipt["dataset_fingerprint"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(DatasetValidationError, match="content"):
        verify_site_dataset_receipt(
            receipt_path,
            manifest,
            site_id="hospital-a",
            verify_content=True,
        )
