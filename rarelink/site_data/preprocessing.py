"""Reproducible hospital-local MONAI preprocessing and persistent caching."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rarelink.site_data.split import deterministic_dataset_split
from rarelink.site_data.validator import (
    DatasetValidationError,
    _file_inventory,
    _load_manifest,
    verify_site_dataset_receipt,
)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class MonaiPreprocessingPlan:
    monai_version: str
    target_spacing: tuple[float, float, float] = (1.0, 1.0, 1.0)
    spatial_divisor: int = 16
    orientation: str = "RAS"

    def __post_init__(self) -> None:
        if (
            not self.monai_version
            or self.monai_version != self.monai_version.strip()
            or any(not math.isfinite(value) or value <= 0 for value in self.target_spacing)
            or len(self.target_spacing) != 3
            or isinstance(self.spatial_divisor, bool)
            or not 1 <= self.spatial_divisor <= 64
            or self.orientation != "RAS"
        ):
            raise ValueError("MONAI preprocessing plan is invalid")

    def specification(self) -> dict[str, Any]:
        return {
            "schema_version": "rarelink-monai-preprocessing-plan-v1",
            "monai_version": self.monai_version,
            "orientation": self.orientation,
            "axis_labels": [["L", "R"], ["P", "A"], ["I", "S"]],
            "target_spacing": list(self.target_spacing),
            "image_interpolation": "bilinear",
            "label_interpolation": "nearest",
            "normalization": {
                "method": "nonzero-zscore",
                "channel_wise": True,
            },
            "spatial_padding": {
                "divisible_by": self.spatial_divisor,
                "mode": "constant",
            },
            "tensor_conversion": True,
            "random_transforms": False,
            "persistent_cache": True,
        }

    @property
    def plan_sha256(self) -> str:
        return hashlib.sha256(_canonical_json(self.specification())).hexdigest()


def default_monai_preprocessing_plan() -> MonaiPreprocessingPlan:
    try:
        import monai
    except ImportError as exc:  # pragma: no cover - optional dependency boundary
        raise RuntimeError(
            "Install RareLink's site-data extra for MONAI preprocessing"
        ) from exc
    return MonaiPreprocessingPlan(monai_version=str(monai.__version__))


def _transforms(
    plan: MonaiPreprocessingPlan,
    label_mapping: dict[str, int] | None,
) -> Any:
    try:
        from monai.transforms import (
            Compose,
            DivisiblePadd,
            EnsureChannelFirstd,
            EnsureTyped,
            LoadImaged,
            MapLabelValued,
            NormalizeIntensityd,
            Orientationd,
            Spacingd,
        )
    except ImportError as exc:  # pragma: no cover - optional dependency boundary
        raise RuntimeError(
            "Install RareLink's site-data extra for MONAI preprocessing"
        ) from exc

    remap = []
    if label_mapping:
        ordered = sorted(
            ((int(source), int(target)) for source, target in label_mapping.items()),
            key=lambda item: item[0],
        )
        remap = [
            MapLabelValued(
                keys=["label"],
                orig_labels=[source for source, _target in ordered],
                target_labels=[target for _source, target in ordered],
            )
        ]
    return Compose(
        [
            LoadImaged(keys=["image", "label"]),
            EnsureChannelFirstd(keys=["image", "label"]),
            Orientationd(
                keys=["image", "label"],
                axcodes=plan.orientation,
                labels=(("L", "R"), ("P", "A"), ("I", "S")),
            ),
            Spacingd(
                keys=["image", "label"],
                pixdim=plan.target_spacing,
                mode=("bilinear", "nearest"),
            ),
            *remap,
            NormalizeIntensityd(
                keys=["image"],
                nonzero=True,
                channel_wise=True,
            ),
            DivisiblePadd(
                keys=["image", "label"],
                k=plan.spatial_divisor,
                mode="constant",
            ),
            EnsureTyped(keys=["image", "label"]),
        ]
    )


def materialize_monai_preprocessing_cache(
    manifest_path: Path,
    receipt_path: Path,
    *,
    site_id: str,
    cache_root: Path,
    data_root: Path | None = None,
    plan: MonaiPreprocessingPlan | None = None,
) -> dict[str, Any]:
    """Verify the approved dataset, then materialize deterministic local caches."""
    try:
        from monai.data import PersistentDataset
    except ImportError as exc:  # pragma: no cover - optional dependency boundary
        raise RuntimeError(
            "Install RareLink's site-data extra for MONAI preprocessing"
        ) from exc

    approved_receipt = verify_site_dataset_receipt(
        receipt_path,
        manifest_path,
        site_id=site_id,
        data_root=data_root,
        verify_content=True,
    )
    preprocessing_plan = plan or default_monai_preprocessing_plan()
    manifest, _manifest_sha256 = _load_manifest(manifest_path)
    approved_root = (data_root or manifest_path.parent).resolve()
    inventory, cases = _file_inventory(
        manifest,
        site_id=site_id,
        data_root=approved_root,
    )
    inventory_by_role = dict(inventory)
    split_receipt = approved_receipt["split"]
    split = deterministic_dataset_split(
        cases,
        seed=split_receipt["seed"],
        validation_fraction=split_receipt["validation_fraction"],
    )
    case_index = {id(case): index for index, case in enumerate(cases)}

    def item(case: dict[str, Any]) -> dict[str, Any]:
        index = case_index[id(case)]
        images = case["images"]
        image_count = 1 if isinstance(images, str) else len(images)
        image_paths = [
            str(inventory_by_role[f"case-{index}:image-{modality_index}"])
            for modality_index in range(image_count)
        ]
        return {
            "image": image_paths[0] if image_count == 1 else image_paths,
            "label": str(inventory_by_role[f"case-{index}:label"]),
        }

    resolved_cache_root = cache_root.resolve()
    if cache_root.is_symlink() or (
        resolved_cache_root.exists() and not resolved_cache_root.is_dir()
    ):
        raise DatasetValidationError("The MONAI cache root is not an approved directory")
    resolved_cache_root.mkdir(parents=True, exist_ok=True)
    transforms = _transforms(
        preprocessing_plan,
        manifest.get("label_mapping"),
    )
    train_dataset = PersistentDataset(
        data=[item(case) for case in split.train_cases],
        transform=transforms,
        cache_dir=resolved_cache_root / "train",
    )
    validation_dataset = PersistentDataset(
        data=[item(case) for case in split.validation_cases],
        transform=transforms,
        cache_dir=resolved_cache_root / "validation",
    )
    for dataset in (train_dataset, validation_dataset):
        for index in range(len(dataset)):
            dataset[index]

    cache_files = sorted(
        path
        for path in resolved_cache_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    cache_content_digests = sorted(_sha256_file(path) for path in cache_files)
    cache_state_sha256 = hashlib.sha256(
        _canonical_json(cache_content_digests)
    ).hexdigest()
    receipt = {
        "schema_version": "rarelink-monai-cache-receipt-v1",
        "prepared_at": datetime.now(UTC).isoformat(),
        "site_id": site_id,
        "passed": True,
        "dataset_fingerprint": approved_receipt["dataset_fingerprint"],
        "preprocessing_plan": preprocessing_plan.specification(),
        "preprocessing_plan_sha256": preprocessing_plan.plan_sha256,
        "split": split.receipt,
        "cached_item_count": len(train_dataset) + len(validation_dataset),
        "cache_file_count": len(cache_files),
        "cache_total_bytes": sum(path.stat().st_size for path in cache_files),
        "cache_state_sha256": cache_state_sha256,
        "cache_is_hospital_local": True,
        "receipt_contains_patient_data": False,
        "case_identifiers_exported": False,
        "file_paths_exported": False,
        "image_or_label_voxels_exported": False,
        "cache_file_names_exported": False,
    }
    return receipt
