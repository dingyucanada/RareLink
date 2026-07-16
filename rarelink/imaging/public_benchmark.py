"""Reproducible public-benchmark preparation for the RareLink demo.

The Medical Segmentation Decathlon (MSD) Task01 data are a *public research
benchmark*.  This module deliberately keeps the raw archive and NIfTI volumes
outside Git and only writes a small, auditable manifest for a selected cohort.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import tarfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rarelink.imaging.synthetic import sha256_file

MSD_TASK01_URL = "https://msd-for-monai.s3-us-west-2.amazonaws.com/Task01_BrainTumour.tar"
MSD_TASK01_MD5 = "240a19d752f0d9e9101544901065d872"
SITE_IDS = ("site-a", "site-b", "site-c")


def _normalise_relative_path(value: str) -> str:
    return value.removeprefix("./")


def _case_id_from_path(value: str) -> str:
    name = Path(value).name
    return name.removesuffix(".nii.gz").removesuffix(".nii")


def _md5_file(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_archive(url: str, destination: Path, expected_md5: str | None = None) -> Path:
    """Download a public archive directly on the compute node and verify it.

    Public research hosts can be slow on shared competition nodes. A retained
    ``.part`` file is resumed with an HTTP Range request when supported; data
    never crosses the operator's SSH connection.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    if destination.exists() and (not expected_md5 or _md5_file(destination) == expected_md5):
        return destination

    resumed_bytes = temporary.stat().st_size if temporary.exists() else 0
    headers = {"User-Agent": "RareLink/0.1 benchmark-preparer"}
    if resumed_bytes:
        headers["Range"] = f"bytes={resumed_bytes}-"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        supports_resume = resumed_bytes > 0 and getattr(response, "status", None) == 206
        if resumed_bytes and not supports_resume:
            resumed_bytes = 0
        mode = "ab" if supports_resume else "wb"
        downloaded = resumed_bytes
        with temporary.open(mode) as output:
            if resumed_bytes:
                print(f"resuming_from_mb={resumed_bytes // (1024 * 1024)}", flush=True)
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                downloaded += len(chunk)
                if downloaded % (256 * 1024 * 1024) < len(chunk):
                    print(f"downloaded_mb={downloaded // (1024 * 1024)}", flush=True)
    temporary.replace(destination)
    if expected_md5 and _md5_file(destination) != expected_md5:
        destination.unlink(missing_ok=True)
        raise ValueError("Downloaded MSD archive failed its published MD5 verification")
    return destination


def safe_extract_tar(archive: Path, destination: Path) -> None:
    """Extract a trusted archive without allowing path traversal entries."""
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        for member in members:
            target = (destination / member.name).resolve()
            if os.path.commonpath((str(root), str(target))) != str(root):
                raise ValueError(f"Unsafe archive member: {member.name}")
        bundle.extractall(destination, members=members, filter="data")


def _quantile_partition(
    cases: list[dict[str, Any]], cases_per_site: int, seed: int
) -> list[dict[str, Any]]:
    """Create deterministic non-IID sites by tumour-volume quantile.

    This is an engineering simulation of cohort shift, not a claim about a
    hospital's patient population.  Each selected site gets cases only from one
    third of the public cohort: low, medium, or high tumour burden.
    """
    if cases_per_site < 2:
        raise ValueError("cases_per_site must be at least 2 for train/validation evaluation")
    if len(cases) < cases_per_site * len(SITE_IDS):
        raise ValueError("The supplied benchmark cohort is too small for three sites")
    ordered = sorted(cases, key=lambda item: (int(item["tumor_voxels"]), item["case_id"]))
    base, remainder = divmod(len(ordered), len(SITE_IDS))
    groups: list[list[dict[str, Any]]] = []
    cursor = 0
    for index in range(len(SITE_IDS)):
        size = base + (1 if index < remainder else 0)
        groups.append(ordered[cursor : cursor + size])
        cursor += size
    if any(len(group) < cases_per_site for group in groups):
        raise ValueError("One tumour-volume quantile does not contain enough cases")

    selected: list[dict[str, Any]] = []
    cohorts = ("low_tumor_burden", "mid_tumor_burden", "high_tumor_burden")
    for index, (site_id, cohort, group) in enumerate(zip(SITE_IDS, cohorts, groups, strict=True)):
        rng = random.Random(seed + index)
        picked = sorted(rng.sample(group, cases_per_site), key=lambda item: item["case_id"])
        for item in picked:
            selected.append({**item, "site_id": site_id, "partition_cohort": cohort})
    return selected


def create_msd_manifest(
    source_dir: Path,
    output_root: Path,
    cases_per_site: int = 8,
    seed: int = 2026,
    archive_path: Path | None = None,
    hash_selected_files: bool = True,
) -> dict[str, Any]:
    """Create an auditable MSD Task01 manifest without copying raw imaging data."""
    try:
        import nibabel as nib
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Install the RareLink spark extra to prepare the MSD benchmark") from exc

    dataset_json = source_dir / "dataset.json"
    if not dataset_json.exists():
        raise FileNotFoundError(f"MSD dataset.json not found under {source_dir}")
    source = json.loads(dataset_json.read_text(encoding="utf-8"))
    raw_cases: list[dict[str, Any]] = []
    for entry in source.get("training", []):
        image_relative = _normalise_relative_path(entry["image"])
        label_relative = _normalise_relative_path(entry["label"])
        label_path = source_dir / label_relative
        if not label_path.exists():
            raise FileNotFoundError(label_path)
        label = np.asanyarray(nib.load(label_path).dataobj)
        image_path = source_dir / image_relative
        spacing = nib.load(image_path).header.get_zooms()[:3]
        raw_cases.append(
            {
                "case_id": _case_id_from_path(image_relative),
                "image_path": image_path,
                "label_path": label_path,
                "tumor_voxels": int(np.count_nonzero(label)),
                "spacing": [round(float(value), 6) for value in spacing],
            }
        )
    selected = _quantile_partition(raw_cases, cases_per_site=cases_per_site, seed=seed)
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_cases: list[dict[str, Any]] = []
    for case in selected:
        image_relative = os.path.relpath(case["image_path"], output_root)
        label_relative = os.path.relpath(case["label_path"], output_root)
        hashes: dict[str, str] = {}
        if hash_selected_files:
            hashes = {
                image_relative: sha256_file(case["image_path"]),
                label_relative: sha256_file(case["label_path"]),
            }
        manifest_cases.append(
            {
                "case_id": case["case_id"],
                "site_id": case["site_id"],
                "images": image_relative,
                "label": label_relative,
                "spacing": case["spacing"],
                "tumor_voxels": case["tumor_voxels"],
                "partition_cohort": case["partition_cohort"],
                "synthetic": False,
                "sha256": hashes,
            }
        )
    manifest = {
        "dataset_id": "msd-task01-brain-tumour-v1",
        "description": "Public MSD Task01 brain tumour engineering benchmark",
        "research_use_only": True,
        "clinical_use_prohibited": True,
        "contains_patient_data": True,
        "public_benchmark": True,
        "seed": seed,
        "sites": list(SITE_IDS),
        "modalities": ["FLAIR", "T1w", "T1wCE", "T2w"],
        "label_mapping": {"0": 0, "1": 1, "2": 2, "4": 2},
        "partition": {
            "method": "tumor_volume_quantiles",
            "simulation_only": True,
            "cases_per_site": cases_per_site,
            "cohorts": ["low_tumor_burden", "mid_tumor_burden", "high_tumor_burden"],
        },
        "source": {
            "name": "Medical Segmentation Decathlon Task01_BrainTumour",
            "url": MSD_TASK01_URL,
            "license": "CC-BY-SA-4.0",
            "archive_md5": (
                _md5_file(archive_path) if archive_path and archive_path.exists() else None
            ),
            "archive_sha256": sha256_file(archive_path)
            if archive_path and archive_path.exists()
            else None,
            "prepared_at_utc": datetime.now(UTC).isoformat(),
        },
        "cases": manifest_cases,
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def prepare_msd_task01(
    data_root: Path,
    manifest_root: Path,
    cases_per_site: int = 8,
    seed: int = 2026,
    url: str = MSD_TASK01_URL,
    skip_hashes: bool = False,
) -> dict[str, Any]:
    """Download, safely unpack, and partition MSD Task01 on the current node."""
    archive = data_root / "Task01_BrainTumour.tar"
    source_dir = data_root / "Task01_BrainTumour"
    if not source_dir.exists():
        expected_md5 = MSD_TASK01_MD5 if url == MSD_TASK01_URL else None
        download_archive(url, archive, expected_md5=expected_md5)
        safe_extract_tar(archive, data_root)
    return create_msd_manifest(
        source_dir=source_dir,
        output_root=manifest_root,
        cases_per_site=cases_per_site,
        seed=seed,
        archive_path=archive if archive.exists() else None,
        hash_selected_files=not skip_hashes,
    )
