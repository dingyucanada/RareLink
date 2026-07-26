from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from rarelink.site_data import (
    BIDSDependencyError,
    DatasetValidationError,
    import_bids_manifest,
    inspect_local_dicom_headers,
    validate_nifti_intake_boundary,
)

nib = pytest.importorskip("nibabel")

MODALITY_QUERIES = {
    "FLAIR": {"suffix": "FLAIR"},
    "T1w": {"suffix": "T1w"},
    "T1wCE": {"suffix": "T1wCE"},
    "T2w": {"suffix": "T2w"},
}
LABEL_QUERY = {"suffix": "seg", "scope": "derivatives"}


class FakeBIDSLayout:
    def __init__(self, root: Path, *, ambiguous: bool = False) -> None:
        self.root = root
        self.ambiguous = ambiguous

    def get_subjects(self) -> list[str]:
        return ["secret-subject-one", "secret-subject-two"]

    def get_sessions(self, *, subject: str) -> list[str]:
        return []

    def get(self, **query: Any) -> list[str]:
        path = self.root / f"sub-{query['subject']}_{query['suffix']}.nii.gz"
        matches = [str(path)]
        return matches * 2 if self.ambiguous else matches


@dataclass(frozen=True)
class FakeTag:
    is_private: bool = False


@dataclass(frozen=True)
class FakeElement:
    keyword: str
    value: Any
    tag: FakeTag = FakeTag()


class FakeDICOMDataset:
    def __init__(
        self,
        *,
        patient_name: str = "",
        private_tag: bool = False,
        uid: str = "1.2.826.0.1.3680043.10.543.secret",
    ) -> None:
        self.values = {
            "PatientIdentityRemoved": "YES",
            "BurnedInAnnotation": "NO",
            "DeidentificationMethod": "Basic Application Confidentiality Profile",
        }
        self.elements = [
            FakeElement("PatientIdentityRemoved", "YES"),
            FakeElement("BurnedInAnnotation", "NO"),
            FakeElement(
                "DeidentificationMethod",
                "Basic Application Confidentiality Profile",
            ),
            FakeElement("PatientName", patient_name),
            FakeElement("PatientID", ""),
            FakeElement("StudyInstanceUID", uid),
            FakeElement("SeriesInstanceUID", f"{uid}.1"),
        ]
        if private_tag:
            self.elements.append(
                FakeElement("", "private-value", FakeTag(is_private=True))
            )

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def iterall(self) -> list[FakeElement]:
        return self.elements


def create_bids_files(root: Path) -> None:
    root.mkdir(parents=True)
    for subject in ("secret-subject-one", "secret-subject-two"):
        for suffix in ("FLAIR", "T1w", "T1wCE", "T2w", "seg"):
            (root / f"sub-{subject}_{suffix}.nii.gz").write_bytes(b"local-nifti")


def create_local_nifti_manifest(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    cases = []
    for case_index in range(2):
        images = []
        for modality_index in range(4):
            path = root / f"private-{case_index}-modality-{modality_index}.nii.gz"
            nib.save(
                nib.Nifti1Image(
                    np.ones((5, 5, 5), dtype=np.float32),
                    np.eye(4),
                ),
                path,
            )
            images.append(path.name)
        label_path = root / f"private-{case_index}-label.nii.gz"
        nib.save(
            nib.Nifti1Image(
                np.zeros((5, 5, 5), dtype=np.uint8),
                np.eye(4),
            ),
            label_path,
        )
        cases.append(
            {
                "case_id": f"opaque-local-{case_index}",
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


def test_pybids_adapter_writes_local_manifest_but_returns_aggregate_receipt(
    tmp_path: Path,
) -> None:
    bids_root = tmp_path / "bids"
    create_bids_files(bids_root)
    output_manifest = tmp_path / "approved" / "manifest.json"

    receipt = import_bids_manifest(
        bids_root,
        output_manifest,
        site_id="hospital-a",
        modality_queries=MODALITY_QUERIES,
        label_query=LABEL_QUERY,
        case_id_key=b"x" * 32,
        layout_factory=lambda _root: FakeBIDSLayout(bids_root),
    )

    manifest = json.loads(output_manifest.read_text(encoding="utf-8"))
    assert len(manifest["cases"]) == 2
    assert all(case["case_id"].startswith("rl-") for case in manifest["cases"])
    assert all(
        "secret-subject" not in case["case_id"]
        for case in manifest["cases"]
    )
    assert receipt["case_count"] == 2
    serialized = json.dumps(receipt)
    assert "secret-subject" not in serialized
    assert str(tmp_path) not in serialized
    assert receipt["subject_entities_exported"] is False
    assert receipt["source_paths_exported"] is False


def test_real_pybids_indexes_two_complete_local_cases(tmp_path: Path) -> None:
    bids_root = tmp_path / "real-bids"
    bids_root.mkdir()
    (bids_root / "dataset_description.json").write_text(
        json.dumps(
            {
                "Name": "RareLink local adapter test",
                "BIDSVersion": "1.10.1",
                "DatasetType": "raw",
            }
        ),
        encoding="utf-8",
    )
    derivatives = bids_root / "derivatives" / "labels"
    derivatives.mkdir(parents=True)
    (derivatives / "dataset_description.json").write_text(
        json.dumps(
            {
                "Name": "RareLink local labels",
                "BIDSVersion": "1.10.1",
                "DatasetType": "derivative",
                "GeneratedBy": [{"Name": "RareLink adapter test"}],
            }
        ),
        encoding="utf-8",
    )
    for subject in ("01", "02"):
        anat = bids_root / f"sub-{subject}" / "anat"
        label_anat = derivatives / f"sub-{subject}" / "anat"
        anat.mkdir(parents=True)
        label_anat.mkdir(parents=True)
        for name in (
            f"sub-{subject}_FLAIR.nii.gz",
            f"sub-{subject}_acq-pre_T1w.nii.gz",
            f"sub-{subject}_acq-ce_T1w.nii.gz",
            f"sub-{subject}_T2w.nii.gz",
        ):
            nib.save(
                nib.Nifti1Image(np.ones((4, 4, 4), dtype=np.float32), np.eye(4)),
                anat / name,
            )
        nib.save(
            nib.Nifti1Image(np.zeros((4, 4, 4), dtype=np.uint8), np.eye(4)),
            label_anat / f"sub-{subject}_desc-tumor_dseg.nii.gz",
        )

    receipt = import_bids_manifest(
        bids_root,
        tmp_path / "real-bids-manifest.json",
        site_id="hospital-a",
        modality_queries={
            "FLAIR": {"suffix": "FLAIR"},
            "T1w": {"suffix": "T1w", "acquisition": "pre"},
            "T1wCE": {"suffix": "T1w", "acquisition": "ce"},
            "T2w": {"suffix": "T2w"},
        },
        label_query={"suffix": "dseg", "desc": "tumor", "scope": "derivatives"},
        case_id_key=b"real-pybids-adapter-test-key-0001",
    )

    assert receipt["passed"] is True
    assert receipt["case_count"] == 2
    assert receipt["subject_entities_exported"] is False


def test_pybids_adapter_fails_closed_when_mapping_is_ambiguous(tmp_path: Path) -> None:
    bids_root = tmp_path / "bids"
    create_bids_files(bids_root)

    with pytest.raises(DatasetValidationError, match="exactly one"):
        import_bids_manifest(
            bids_root,
            tmp_path / "manifest.json",
            site_id="hospital-a",
            modality_queries=MODALITY_QUERIES,
            label_query=LABEL_QUERY,
            case_id_key=b"x" * 32,
            layout_factory=lambda _root: FakeBIDSLayout(
                bids_root,
                ambiguous=True,
            ),
        )


def test_pybids_optional_dependency_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bids_root = tmp_path / "bids"
    create_bids_files(bids_root)
    monkeypatch.setitem(sys.modules, "bids", None)

    with pytest.raises(BIDSDependencyError, match="site-data"):
        import_bids_manifest(
            bids_root,
            tmp_path / "manifest.json",
            site_id="hospital-a",
            modality_queries=MODALITY_QUERIES,
            label_query=LABEL_QUERY,
            case_id_key=b"x" * 32,
        )


def test_dicom_header_receipt_never_exports_uid_patient_value_or_path(
    tmp_path: Path,
) -> None:
    dicom_root = tmp_path / "dicom"
    dicom_root.mkdir()
    paths = [dicom_root / "first.dcm", dicom_root / "second.dcm"]
    for path in paths:
        path.write_bytes(b"not-read-by-fake-reader")
    uid_sentinel = "1.2.826.0.1.3680043.10.543.987654321"

    receipt = inspect_local_dicom_headers(
        paths,
        data_root=dicom_root,
        reader=lambda _path: FakeDICOMDataset(uid=uid_sentinel),
    )

    assert receipt["passed"] is True
    assert receipt["inspected_file_count"] == 2
    assert receipt["pixel_data_read"] is False
    serialized = json.dumps(receipt)
    assert uid_sentinel not in serialized
    assert "PatientName" not in serialized
    assert "first.dcm" not in serialized
    assert str(tmp_path) not in serialized


def test_real_pydicom_reader_checks_header_without_pixel_access(tmp_path: Path) -> None:
    pytest.importorskip("pydicom")
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    dicom_root = tmp_path / "real-dicom"
    dicom_root.mkdir()
    paths: list[Path] = []
    for index in range(2):
        path = dicom_root / f"deidentified-{index}.dcm"
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID = generate_uid()
        meta.MediaStorageSOPInstanceUID = generate_uid()
        dataset = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
        dataset.PatientIdentityRemoved = "YES"
        dataset.BurnedInAnnotation = "NO"
        dataset.DeidentificationMethod = "Basic Application Confidentiality Profile"
        dataset.PatientName = ""
        dataset.PatientID = ""
        dataset.StudyInstanceUID = generate_uid()
        dataset.SeriesInstanceUID = generate_uid()
        dataset.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
        dataset.SOPClassUID = meta.MediaStorageSOPClassUID
        dataset.save_as(path, enforce_file_format=True)
        paths.append(path)

    receipt = inspect_local_dicom_headers(paths, data_root=dicom_root)

    assert receipt["passed"] is True
    assert receipt["inspected_file_count"] == 2
    assert receipt["pixel_data_read"] is False
    assert receipt["patient_metadata_exported"] is False


@pytest.mark.parametrize(
    "dataset",
    [
        FakeDICOMDataset(patient_name="sensitive-patient-name"),
        FakeDICOMDataset(private_tag=True),
    ],
)
def test_dicom_header_check_rejects_identifier_or_private_tag_without_echo(
    tmp_path: Path,
    dataset: FakeDICOMDataset,
) -> None:
    dicom_root = tmp_path / "dicom"
    dicom_root.mkdir()
    path = dicom_root / "input.dcm"
    path.write_bytes(b"local")

    with pytest.raises(DatasetValidationError) as captured:
        inspect_local_dicom_headers(
            [path],
            data_root=dicom_root,
            reader=lambda _path: dataset,
        )

    assert "sensitive-patient-name" not in str(captured.value)
    assert str(path) not in str(captured.value)


def test_dicom_receipt_can_bind_nifti_intake_without_converting_or_exporting(
    tmp_path: Path,
) -> None:
    dicom_root = tmp_path / "dicom"
    dicom_root.mkdir()
    dicom_path = dicom_root / "input.dcm"
    dicom_path.write_bytes(b"local")
    dicom_receipt = inspect_local_dicom_headers(
        [dicom_path],
        data_root=dicom_root,
        reader=lambda _path: FakeDICOMDataset(),
    )
    manifest = create_local_nifti_manifest(tmp_path / "nifti")

    receipt = validate_nifti_intake_boundary(
        manifest,
        site_id="hospital-a",
        source_dicom_receipt=dicom_receipt,
    )

    assert receipt["passed"] is True
    assert receipt["intake_boundary"]["source_format"] == "DICOM-derived NIfTI"
    assert receipt["intake_boundary"]["dicom_header_receipt_bound"] is True
    assert receipt["intake_boundary"]["pacs_connected"] is False
    assert receipt["intake_boundary"]["dicom_conversion_performed"] is False
    serialized = json.dumps(receipt)
    assert "opaque-local" not in serialized
    assert "private-" not in serialized
