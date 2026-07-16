import json
from pathlib import Path
from typing import Any


def _normalize_slice(np, image):  # type: ignore[no-untyped-def]
    finite = image[np.isfinite(image)]
    nonzero = finite[finite != 0]
    values = nonzero if nonzero.size else finite
    if not values.size:
        return np.zeros_like(image, dtype=np.uint8)
    low, high = np.percentile(values, [1, 99])
    if high <= low:
        return np.zeros_like(image, dtype=np.uint8)
    normalized = np.clip((image - low) / (high - low), 0.0, 1.0)
    return np.rint(normalized * 255).astype(np.uint8)


def _downsample(np, image, max_size: int):  # type: ignore[no-untyped-def]
    height, width = image.shape
    target_height = min(height, max_size)
    target_width = min(width, max_size)
    rows = np.linspace(0, height - 1, target_height).astype(int)
    columns = np.linspace(0, width - 1, target_width).astype(int)
    return image[np.ix_(rows, columns)]


def build_synthetic_imaging_preview(
    manifest_path: Path,
    site_id: str,
    max_size: int = 64,
) -> dict[str, Any]:
    """Return display-only arrays for a synthetic case; never expose source paths."""
    try:
        import nibabel as nib
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("nibabel and numpy are required for imaging previews") from exc

    if not 16 <= max_size <= 128:
        raise ValueError("max_size must be between 16 and 128")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("contains_patient_data") is not False:
        raise PermissionError("Preview API is restricted to non-clinical synthetic data")
    cases = [case for case in manifest.get("cases", []) if case.get("site_id") == site_id]
    if not cases:
        raise ValueError(f"No synthetic preview case for site {site_id!r}")
    case = cases[0]
    root = manifest_path.parent
    label_volume = np.asanyarray(nib.load(root / case["label"]).dataobj)
    if label_volume.ndim != 3:
        raise ValueError("Preview label must be a 3D volume")
    foreground_by_slice = np.count_nonzero(label_volume, axis=(0, 1))
    slice_index = int(np.argmax(foreground_by_slice))
    label_slice = _downsample(np, label_volume[:, :, slice_index], max_size).astype(np.uint8)

    image_value = case["images"]
    modality_names = list(manifest.get("modalities", ["T1", "T1CE", "T2", "FLAIR"]))
    volumes = []
    if isinstance(image_value, str):
        volume = np.asanyarray(nib.load(root / image_value).dataobj)
        if volume.ndim != 4:
            raise ValueError("Single-file preview image must contain four channels")
        volumes = [volume[..., index] for index in range(volume.shape[-1])]
    else:
        volumes = [np.asanyarray(nib.load(root / value).dataobj) for value in image_value]
    if len(volumes) != len(modality_names):
        raise ValueError("Preview modality count does not match manifest")

    modalities = []
    for name, volume in zip(modality_names, volumes, strict=True):
        image_slice = _downsample(np, volume[:, :, slice_index], max_size)
        normalized = _normalize_slice(np, image_slice)
        modalities.append({"name": name, "pixels": normalized.tolist()})
    unique, counts = np.unique(label_slice, return_counts=True)
    return {
        "dataset_id": manifest.get("dataset_id"),
        "site_id": site_id,
        "case_id": case["case_id"],
        "synthetic": True,
        "research_use_only": True,
        "sent_to_llm": False,
        "slice_axis": "axial",
        "slice_index": slice_index,
        "shape": list(label_slice.shape),
        "spacing": case.get("spacing"),
        "label_pixels": label_slice.tolist(),
        "label_counts": {
            str(int(label)): int(count) for label, count in zip(unique, counts, strict=True)
        },
        "modalities": modalities,
    }
