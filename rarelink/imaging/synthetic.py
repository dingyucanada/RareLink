import hashlib
import json
from pathlib import Path
from typing import Any

SITE_PROFILES = {
    "site-a": {"noise": 0.035, "bias": 0.00, "spacing": (1.0, 1.0, 1.2)},
    "site-b": {"noise": 0.055, "bias": 0.08, "spacing": (0.9, 0.9, 1.0)},
    "site-c": {"noise": 0.085, "bias": -0.06, "spacing": (1.2, 1.2, 2.0)},
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ellipsoid(np, grid, center, radii):  # type: ignore[no-untyped-def]
    distance = sum(
        ((axis - coordinate) / radius) ** 2
        for axis, coordinate, radius in zip(grid, center, radii, strict=True)
    )
    return distance <= 1.0


def generate_synthetic_dataset(
    output_root: Path,
    cases_per_site: int = 4,
    shape: tuple[int, int, int] = (32, 32, 32),
    seed: int = 2026,
) -> dict[str, Any]:
    """Generate a tiny, non-clinical four-modal NIfTI cohort for engineering tests."""
    try:
        import nibabel as nib
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Install the RareLink spark extra to generate NIfTI data") from exc

    if cases_per_site < 2:
        raise ValueError(
            "At least two cases per site are required for train/validation smoke tests"
        )
    if any(size < 16 for size in shape):
        raise ValueError("Synthetic volume dimensions must be at least 16 voxels")

    output_root.mkdir(parents=True, exist_ok=True)
    grid = np.meshgrid(
        *[np.linspace(-1.0, 1.0, size, dtype=np.float32) for size in shape],
        indexing="ij",
    )
    radial = np.sqrt(sum(axis**2 for axis in grid))
    brain_mask = radial < 0.92
    cases: list[dict[str, Any]] = []

    for site_index, (site_id, profile) in enumerate(SITE_PROFILES.items()):
        site_root = output_root / site_id
        site_root.mkdir(exist_ok=True)
        for case_index in range(cases_per_site):
            case_id = f"{site_id}-case-{case_index + 1:03d}"
            rng = np.random.default_rng(seed + site_index * 1000 + case_index)
            center = (
                rng.uniform(-0.25, 0.25),
                rng.uniform(-0.22, 0.22),
                rng.uniform(-0.18, 0.18),
            )
            radii = (
                rng.uniform(0.14, 0.25),
                rng.uniform(0.12, 0.23),
                rng.uniform(0.12, 0.22),
            )
            tumor = _ellipsoid(np, grid, center, radii) & brain_mask
            edema = (
                _ellipsoid(np, grid, center, tuple(radius * 1.65 for radius in radii)) & brain_mask
            )
            edema = edema & ~tumor
            label = np.zeros(shape, dtype=np.uint8)
            label[edema] = 1
            label[tumor] = 2

            base = np.clip(1.0 - radial, 0.0, 1.0) * brain_mask
            modality_contrasts = [
                (0.65, 0.55, 0.25),
                (0.75, 1.10, 0.35),
                (0.55, 0.65, 0.85),
                (0.50, 0.75, 1.20),
            ]
            affine = np.diag([*profile["spacing"], 1.0]).astype(np.float32)
            image_paths: list[str] = []
            hashes: dict[str, str] = {}
            for modality_index, (base_scale, tumor_scale, edema_scale) in enumerate(
                modality_contrasts
            ):
                image = base * base_scale
                image = image + tumor.astype(np.float32) * tumor_scale
                image = image + edema.astype(np.float32) * edema_scale
                image = image + float(profile["bias"]) * grid[0]
                image = image + rng.normal(0.0, float(profile["noise"]), shape)
                image = np.clip(image, 0.0, None).astype(np.float32)
                image_path = site_root / f"{case_id}-modality-{modality_index}.nii.gz"
                nib.save(nib.Nifti1Image(image, affine), image_path)
                image_paths.append(str(image_path.relative_to(output_root)))
                hashes[image_paths[-1]] = sha256_file(image_path)

            label_path = site_root / f"{case_id}-label.nii.gz"
            nib.save(nib.Nifti1Image(label, affine), label_path)
            relative_label = str(label_path.relative_to(output_root))
            hashes[relative_label] = sha256_file(label_path)
            cases.append(
                {
                    "case_id": case_id,
                    "site_id": site_id,
                    "images": image_paths,
                    "label": relative_label,
                    "spacing": list(profile["spacing"]),
                    "synthetic": True,
                    "sha256": hashes,
                }
            )

    manifest = {
        "dataset_id": "synthetic-demo-v1",
        "description": "Programmatically generated non-clinical NIfTI cohort",
        "research_use_only": True,
        "contains_patient_data": False,
        "seed": seed,
        "shape": list(shape),
        "modalities": ["T1", "T1CE", "T2", "FLAIR"],
        "sites": list(SITE_PROFILES),
        "cases": cases,
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
