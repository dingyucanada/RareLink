"""Validate one hospital's NIfTI manifest without exporting case-level data."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rarelink.site_data.split import DatasetSplitError, deterministic_dataset_split

FORBIDDEN_IDENTIFIER_KEYS = {
    "accession_number",
    "birth_date",
    "date_of_birth",
    "dicom_uid",
    "medical_record_number",
    "mrn",
    "patient_id",
    "patient_name",
    "patient_phone",
    "patient_email",
    "study_instance_uid",
    "series_instance_uid",
}
NIFTI_SUFFIXES = (".nii", ".nii.gz")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DatasetValidationError(ValueError):
    """Safe local validation error that never includes a case ID or path."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _load_manifest(manifest_path: Path) -> tuple[dict[str, Any], str]:
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise DatasetValidationError("The local dataset manifest is unavailable")
    try:
        raw = manifest_path.read_bytes()
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetValidationError("The local dataset manifest is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise DatasetValidationError("The local dataset manifest must be a JSON object")
    return payload, hashlib.sha256(raw).hexdigest()


def _reject_identifiers(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).strip().lower() in FORBIDDEN_IDENTIFIER_KEYS:
                raise DatasetValidationError(
                    "The local manifest contains a forbidden direct-identifier field"
                )
            _reject_identifiers(child)
    elif isinstance(value, list):
        for child in value:
            _reject_identifiers(child)


def _case_paths(case: dict[str, Any]) -> tuple[list[str], str]:
    images = case.get("images")
    label = case.get("label")
    if isinstance(images, str):
        image_paths = [images]
    elif isinstance(images, list) and all(isinstance(item, str) for item in images):
        image_paths = list(images)
    else:
        raise DatasetValidationError(
            "Every case must declare one four-channel image or four modality files"
        )
    if len(image_paths) not in {1, 4} or not isinstance(label, str):
        raise DatasetValidationError(
            "Every case must declare one four-channel image or four modality files and one label"
        )
    return image_paths, label


def _resolve_local_nifti(data_root: Path, value: str) -> Path:
    if not value or "\x00" in value:
        raise DatasetValidationError("A declared NIfTI reference is invalid")
    candidate = Path(value)
    resolved = (
        candidate.resolve() if candidate.is_absolute() else (data_root / candidate).resolve()
    )
    try:
        resolved.relative_to(data_root)
    except ValueError as exc:
        raise DatasetValidationError(
            "A declared NIfTI reference escapes the approved local data root"
        ) from exc
    lower_name = resolved.name.lower()
    if not lower_name.endswith(NIFTI_SUFFIXES):
        raise DatasetValidationError("Only .nii and .nii.gz files are accepted")
    if not resolved.is_file() or resolved.is_symlink():
        raise DatasetValidationError("A declared NIfTI file is missing or not a regular file")
    return resolved


def _manifest_cases(
    manifest: dict[str, Any],
    *,
    site_id: str,
) -> list[dict[str, Any]]:
    _reject_identifiers(manifest)
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise DatasetValidationError("The local manifest must contain a non-empty cases list")
    if not all(isinstance(case, dict) for case in cases):
        raise DatasetValidationError("Every manifest case must be a JSON object")
    site_ids = {str(case.get("site_id", "")) for case in cases}
    if site_ids != {site_id}:
        raise DatasetValidationError(
            "The physical-site manifest must contain only the configured local Site ID"
        )
    modalities = manifest.get("modalities")
    if not isinstance(modalities, list) or len(modalities) != 4:
        raise DatasetValidationError("The physical MRI manifest must declare four modalities")
    for case in cases:
        _case_paths(case)
    return cases  # type: ignore[return-value]


def _file_inventory(
    manifest: dict[str, Any],
    *,
    site_id: str,
    data_root: Path,
) -> tuple[list[tuple[str, Path]], list[dict[str, Any]]]:
    cases = _manifest_cases(manifest, site_id=site_id)
    inventory: list[tuple[str, Path]] = []
    for case_index, case in enumerate(cases):
        images, label = _case_paths(case)
        for modality_index, image in enumerate(images):
            inventory.append(
                (
                    f"case-{case_index}:image-{modality_index}",
                    _resolve_local_nifti(data_root, image),
                )
            )
        inventory.append(
            (f"case-{case_index}:label", _resolve_local_nifti(data_root, label))
        )
    return inventory, cases


def _file_state_fingerprint(
    manifest_sha256: str,
    inventory: list[tuple[str, Path]],
) -> str:
    state = [
        {
            "role": role,
            "size": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns,
        }
        for role, path in inventory
    ]
    return hashlib.sha256(
        _canonical_json({"manifest_sha256": manifest_sha256, "files": state})
    ).hexdigest()


def current_file_state_fingerprint(
    manifest_path: Path,
    *,
    site_id: str,
    data_root: Path | None = None,
) -> tuple[str, str]:
    """Return manifest and cheap file-state fingerprints without loading voxels."""
    manifest, manifest_sha256 = _load_manifest(manifest_path)
    approved_root = (data_root or manifest_path.parent).resolve()
    inventory, _cases = _file_inventory(
        manifest,
        site_id=site_id,
        data_root=approved_root,
    )
    return manifest_sha256, _file_state_fingerprint(manifest_sha256, inventory)


def _allowed_label_values(manifest: dict[str, Any]) -> set[int]:
    mapping = manifest.get("label_mapping")
    if isinstance(mapping, dict) and mapping:
        try:
            return {int(value) for value in mapping}
        except (TypeError, ValueError) as exc:
            raise DatasetValidationError("label_mapping keys must be integer labels") from exc
    values = manifest.get("allowed_label_values", [0, 1, 2])
    if (
        not isinstance(values, list)
        or not values
        or any(not isinstance(value, int) or isinstance(value, bool) for value in values)
    ):
        raise DatasetValidationError("allowed_label_values must be a non-empty integer list")
    return set(values)


def validate_site_dataset(
    manifest_path: Path,
    *,
    site_id: str,
    data_root: Path | None = None,
    split_seed: int = 2026,
    validation_fraction: float = 0.2,
) -> dict[str, Any]:
    """Run explicit NIfTI geometry/label validation and emit a safe receipt."""
    try:
        import nibabel as nib
        import numpy as np
    except ImportError as exc:  # pragma: no cover - guarded CLI dependency
        raise RuntimeError("Install RareLink's spark extra for NIfTI validation") from exc

    manifest, manifest_sha256 = _load_manifest(manifest_path)
    approved_root = (data_root or manifest_path.parent).resolve()
    inventory, cases = _file_inventory(
        manifest,
        site_id=site_id,
        data_root=approved_root,
    )
    try:
        split = deterministic_dataset_split(
            cases,
            seed=split_seed,
            validation_fraction=validation_fraction,
        )
    except DatasetSplitError as exc:
        raise DatasetValidationError(str(exc)) from None
    allowed_labels = _allowed_label_values(manifest)
    shape_variants: set[tuple[int, int, int]] = set()
    spacing_variants: set[tuple[float, float, float]] = set()
    orientation_variants: set[tuple[str, str, str]] = set()
    observed_labels: set[int] = set()

    content_digest = hashlib.sha256()
    content_digest.update(bytes.fromhex(manifest_sha256))
    inventory_by_role = dict(inventory)
    for role, path in inventory:
        content_digest.update(role.encode("utf-8"))
        content_digest.update(bytes.fromhex(_sha256_file(path)))

    for case_index, case in enumerate(cases):
        image_values, label_value = _case_paths(case)
        image_paths = [
            inventory_by_role[f"case-{case_index}:image-{index}"]
            for index in range(len(image_values))
        ]
        label_path = inventory_by_role[f"case-{case_index}:label"]
        label = nib.load(str(label_path))
        label_shape = tuple(int(value) for value in label.shape)
        if len(label_shape) != 3:
            raise DatasetValidationError("Segmentation labels must be three-dimensional")
        if not np.all(np.isfinite(label.affine)):
            raise DatasetValidationError("A label affine contains non-finite values")
        case_orientation = tuple(str(value) for value in nib.aff2axcodes(label.affine))
        label_values = np.asanyarray(label.dataobj)
        if not np.all(np.isfinite(label_values)):
            raise DatasetValidationError("A segmentation label contains non-finite values")
        rounded = np.rint(label_values)
        if not np.allclose(label_values, rounded):
            raise DatasetValidationError("Segmentation labels must contain integer class values")
        case_labels = {int(value) for value in np.unique(rounded)}
        if not case_labels.issubset(allowed_labels):
            raise DatasetValidationError(
                "A segmentation label contains values outside the approved label contract"
            )
        observed_labels.update(case_labels)

        for image_path in image_paths:
            image = nib.load(str(image_path))
            image_shape = tuple(int(value) for value in image.shape)
            if len(image_paths) == 1:
                if len(image_shape) != 4 or image_shape[-1] != 4:
                    raise DatasetValidationError(
                        "A combined MRI image must expose four registered channels"
                    )
                spatial_shape = image_shape[:3]
            else:
                if len(image_shape) != 3:
                    raise DatasetValidationError(
                        "Each separate MRI modality must be three-dimensional"
                    )
                spatial_shape = image_shape
            if spatial_shape != label_shape:
                raise DatasetValidationError("MRI and label spatial shapes do not match")
            if not np.all(np.isfinite(image.affine)):
                raise DatasetValidationError("An MRI affine contains non-finite values")
            if not np.allclose(image.affine, label.affine, rtol=1e-4, atol=1e-4):
                raise DatasetValidationError("MRI modalities and label are not registered")
            orientation = tuple(str(value) for value in nib.aff2axcodes(image.affine))
            if orientation != case_orientation:
                raise DatasetValidationError("MRI and label orientations do not match")
            zooms = tuple(round(float(value), 6) for value in image.header.get_zooms()[:3])
            if any(not math.isfinite(value) or value <= 0 for value in zooms):
                raise DatasetValidationError("MRI voxel spacing must be finite and positive")
            shape_variants.add(spatial_shape)
            spacing_variants.add(zooms)
            orientation_variants.add(orientation)

    file_state = _file_state_fingerprint(manifest_sha256, inventory)
    return {
        "schema_version": "rarelink-site-dataset-receipt-v1",
        "validated_at": datetime.now(UTC).isoformat(),
        "site_id": site_id,
        "passed": True,
        "dataset_fingerprint": content_digest.hexdigest(),
        "manifest_sha256": manifest_sha256,
        "file_state_fingerprint": file_state,
        "case_count": len(cases),
        "file_count": len(inventory),
        "modalities_per_case": 4,
        "geometry": {
            "registered_within_case": True,
            "shape_variant_count": len(shape_variants),
            "spacing_variant_count": len(spacing_variants),
            "orientation_variants": [
                "".join(orientation) for orientation in sorted(orientation_variants)
            ],
        },
        "labels": {
            "allowed_values": sorted(allowed_labels),
            "observed_values": sorted(observed_labels),
            "integer_contract_verified": True,
        },
        "split": split.receipt,
        "receipt_contains_patient_data": False,
        "source_manifest_exported": False,
        "case_identifiers_exported": False,
        "file_paths_exported": False,
        "image_voxels_exported": False,
        "label_voxels_exported": False,
    }


def verify_site_dataset_receipt(
    receipt_path: Path,
    manifest_path: Path,
    *,
    site_id: str,
    data_root: Path | None = None,
    verify_content: bool = False,
) -> dict[str, Any]:
    """Verify a saved receipt against the current local dataset state.

    Heartbeats use the cheap manifest/stat comparison. A training process sets
    ``verify_content=True`` once at startup to re-run geometry, labels, and file
    content hashing before MONAI opens the study for training.
    """
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise DatasetValidationError("The local dataset receipt is unavailable")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DatasetValidationError("The local dataset receipt is invalid") from exc
    if not isinstance(receipt, dict):
        raise DatasetValidationError("The local dataset receipt must be a JSON object")
    safe_flags = (
        receipt.get("receipt_contains_patient_data") is False
        and receipt.get("source_manifest_exported") is False
        and receipt.get("case_identifiers_exported") is False
        and receipt.get("file_paths_exported") is False
        and receipt.get("image_voxels_exported") is False
        and receipt.get("label_voxels_exported") is False
    )
    split_receipt = receipt.get("split")
    try:
        if not isinstance(split_receipt, dict):
            raise DatasetSplitError("Dataset split receipt is unavailable")
        manifest, _manifest_sha256 = _load_manifest(manifest_path)
        cases = _manifest_cases(manifest, site_id=site_id)
        current_split = deterministic_dataset_split(
            cases,
            seed=split_receipt.get("seed"),
            validation_fraction=split_receipt.get("validation_fraction"),
        )
    except DatasetSplitError:
        raise DatasetValidationError(
            "The local dataset split proof is invalid or unavailable"
        ) from None
    split_verified = current_split.receipt == split_receipt
    manifest_sha256, file_state = current_file_state_fingerprint(
        manifest_path,
        site_id=site_id,
        data_root=data_root,
    )
    verified = (
        receipt.get("schema_version") == "rarelink-site-dataset-receipt-v1"
        and receipt.get("passed") is True
        and receipt.get("site_id") == site_id
        and isinstance(receipt.get("dataset_fingerprint"), str)
        and SHA256.fullmatch(receipt["dataset_fingerprint"]) is not None
        and receipt.get("manifest_sha256") == manifest_sha256
        and receipt.get("file_state_fingerprint") == file_state
        and split_verified
        and safe_flags
    )
    if not verified:
        raise DatasetValidationError(
            "The local dataset receipt is stale, mismatched, or not safe to export"
        )
    if verify_content:
        current = validate_site_dataset(
            manifest_path,
            site_id=site_id,
            data_root=data_root,
            split_seed=current_split.receipt["seed"],
            validation_fraction=current_split.receipt["validation_fraction"],
        )
        if current["dataset_fingerprint"] != receipt.get("dataset_fingerprint"):
            raise DatasetValidationError(
                "The current NIfTI content does not match the approved dataset receipt"
            )
    return receipt
