"""Local-only DICOM metadata de-identification checks.

This module does not convert DICOM, connect to PACS, or export header values.
It checks already-staged local headers before separately produced NIfTI files
may enter the RareLink manifest validation boundary.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Protocol

from rarelink.site_data.validator import DatasetValidationError, validate_site_dataset

DIRECT_IDENTIFIER_KEYWORDS = frozenset(
    {
        "AccessionNumber",
        "IssuerOfPatientID",
        "MedicalRecordLocator",
        "OtherPatientIDs",
        "OtherPatientNames",
        "PatientAddress",
        "PatientBirthDate",
        "PatientBirthName",
        "PatientID",
        "PatientMotherBirthName",
        "PatientName",
        "PatientTelephoneNumbers",
        "ReferringPhysicianName",
        "ResponsiblePerson",
        "StudyID",
    }
)
UID_KEYWORDS = frozenset(
    {
        "FrameOfReferenceUID",
        "MediaStorageSOPInstanceUID",
        "ReferencedSOPInstanceUID",
        "SeriesInstanceUID",
        "SOPInstanceUID",
        "StudyInstanceUID",
    }
)
SAFE_DICOM_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "passed",
        "inspected_file_count",
        "dicom_header_set_sha256",
        "identity_removed_verified",
        "burned_in_annotation_absent",
        "private_tags_absent",
        "direct_identifier_values_absent",
        "pixel_data_read",
        "patient_metadata_exported",
        "uid_values_exported",
        "source_paths_exported",
    }
)


class DICOMDependencyError(RuntimeError):
    """Raised when pydicom is not installed at the local site."""


class _DICOMElement(Protocol):
    keyword: str
    value: Any
    tag: Any


class _DICOMDataset(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...

    def iterall(self) -> Iterable[_DICOMElement]: ...


def _default_reader(path: Path) -> _DICOMDataset:
    try:
        import pydicom
    except ImportError as exc:  # pragma: no cover - optional dependency boundary
        raise DICOMDependencyError(
            "Install RareLink's site-data extra to enable pydicom header checks"
        ) from exc
    return pydicom.dcmread(str(path), stop_before_pixels=True, force=False)


def _dataset_value(dataset: _DICOMDataset, keyword: str) -> Any:
    value = dataset.get(keyword)
    return getattr(value, "value", value)


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    try:
        return len(value) > 0
    except TypeError:
        return True


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def inspect_local_dicom_headers(
    dicom_files: list[Path],
    *,
    data_root: Path,
    reader: Callable[[Path], _DICOMDataset] | None = None,
) -> dict[str, Any]:
    """Check staged DICOM headers and return a value-free aggregate receipt."""
    approved_root = data_root.resolve()
    if (
        not approved_root.is_dir()
        or data_root.is_symlink()
        or not isinstance(dicom_files, list)
        or not dicom_files
    ):
        raise DatasetValidationError("The local DICOM intake configuration is invalid")
    resolved_files: list[Path] = []
    for file_path in dicom_files:
        candidate = file_path.resolve()
        try:
            candidate.relative_to(approved_root)
        except ValueError as exc:
            raise DatasetValidationError(
                "A DICOM input escapes the approved local data root"
            ) from exc
        if (
            not candidate.is_file()
            or candidate.is_symlink()
            or candidate.suffix.lower() not in {"", ".dcm"}
        ):
            raise DatasetValidationError(
                "Every DICOM input must be a local regular .dcm or extensionless file"
            )
        resolved_files.append(candidate)
    if len(resolved_files) != len(set(resolved_files)):
        raise DatasetValidationError("The DICOM input list contains duplicate files")

    read_header = reader or _default_reader
    header_bindings: list[str] = []
    for path in sorted(resolved_files):
        try:
            dataset = read_header(path)
            elements = list(dataset.iterall())
        except DICOMDependencyError:
            raise
        except Exception:
            raise DatasetValidationError(
                "A local DICOM header could not be parsed safely"
            ) from None
        if str(_dataset_value(dataset, "PatientIdentityRemoved") or "").upper() != "YES":
            raise DatasetValidationError(
                "DICOM metadata does not assert that patient identity was removed"
            )
        if str(_dataset_value(dataset, "BurnedInAnnotation") or "").upper() != "NO":
            raise DatasetValidationError(
                "DICOM metadata does not rule out burned-in annotation"
            )
        if not _is_present(_dataset_value(dataset, "DeidentificationMethod")):
            raise DatasetValidationError(
                "DICOM metadata does not declare a de-identification method"
            )

        safe_header_projection: list[tuple[str, str]] = []
        for element in elements:
            keyword = str(getattr(element, "keyword", "") or "")
            tag = getattr(element, "tag", None)
            if getattr(tag, "is_private", False):
                raise DatasetValidationError(
                    "DICOM metadata contains a private tag after de-identification"
                )
            value = getattr(element, "value", None)
            if keyword == "PixelData":
                raise DatasetValidationError(
                    "The DICOM metadata reader crossed the pixel-data boundary"
                )
            if keyword in DIRECT_IDENTIFIER_KEYWORDS and _is_present(value):
                raise DatasetValidationError(
                    "DICOM metadata contains a forbidden direct-identifier value"
                )
            if keyword:
                safe_header_projection.append((keyword, str(value)))
        header_bindings.append(
            hashlib.sha256(_canonical_json(safe_header_projection)).hexdigest()
        )

    return {
        "schema_version": "rarelink-dicom-header-receipt-v1",
        "passed": True,
        "inspected_file_count": len(resolved_files),
        "dicom_header_set_sha256": hashlib.sha256(
            _canonical_json(sorted(header_bindings))
        ).hexdigest(),
        "identity_removed_verified": True,
        "burned_in_annotation_absent": True,
        "private_tags_absent": True,
        "direct_identifier_values_absent": True,
        "pixel_data_read": False,
        "patient_metadata_exported": False,
        "uid_values_exported": False,
        "source_paths_exported": False,
    }


def validate_nifti_intake_boundary(
    manifest_path: Path,
    *,
    site_id: str,
    data_root: Path | None = None,
    source_dicom_receipt: dict[str, Any] | None = None,
    split_seed: int = 2026,
    validation_fraction: float = 0.2,
) -> dict[str, Any]:
    """Validate NIfTI input and optionally bind an approved DICOM-header receipt.

    DICOM-to-NIfTI conversion is deliberately outside this function. The
    caller must stage converted NIfTI files and a local manifest first.
    """
    source_format = "NIfTI"
    dicom_binding: str | None = None
    if source_dicom_receipt is not None:
        if (
            not isinstance(source_dicom_receipt, dict)
            or set(source_dicom_receipt) != SAFE_DICOM_RECEIPT_KEYS
            or source_dicom_receipt.get("schema_version")
            != "rarelink-dicom-header-receipt-v1"
            or source_dicom_receipt.get("passed") is not True
            or source_dicom_receipt.get("identity_removed_verified") is not True
            or source_dicom_receipt.get("burned_in_annotation_absent") is not True
            or source_dicom_receipt.get("private_tags_absent") is not True
            or source_dicom_receipt.get("direct_identifier_values_absent") is not True
            or source_dicom_receipt.get("pixel_data_read") is not False
            or source_dicom_receipt.get("patient_metadata_exported") is not False
            or source_dicom_receipt.get("uid_values_exported") is not False
            or source_dicom_receipt.get("source_paths_exported") is not False
        ):
            raise DatasetValidationError(
                "The DICOM source receipt is unsafe or structurally invalid"
            )
        dicom_binding = source_dicom_receipt.get("dicom_header_set_sha256")
        if (
            not isinstance(dicom_binding, str)
            or len(dicom_binding) != 64
            or any(character not in "0123456789abcdef" for character in dicom_binding)
        ):
            raise DatasetValidationError("The DICOM source receipt binding is invalid")
        source_format = "DICOM-derived NIfTI"

    receipt = validate_site_dataset(
        manifest_path,
        site_id=site_id,
        data_root=data_root,
        split_seed=split_seed,
        validation_fraction=validation_fraction,
    )
    receipt["intake_boundary"] = {
        "schema_version": "rarelink-nifti-intake-boundary-v1",
        "source_format": source_format,
        "dicom_header_receipt_bound": dicom_binding is not None,
        "dicom_header_set_sha256": dicom_binding,
        "pacs_connected": False,
        "dicom_conversion_performed": False,
        "patient_metadata_exported": False,
        "uid_values_exported": False,
        "source_paths_exported": False,
    }
    return receipt
