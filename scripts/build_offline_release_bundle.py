#!/usr/bin/env python3
"""Build a deterministic, checksummed ARM64 RareLink offline release bundle."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ARTIFACTS = {
    "python-wheel",
    "python-sdist",
    "coordinator-arm64-image",
    "web-arm64-image",
    "source-sbom",
    "coordinator-sbom",
    "web-sbom",
    "vulnerability-report",
}
STATIC_FILES = {
    "deploy/offline/compose.yml": PROJECT_ROOT / "deploy/offline/compose.yml",
    "deploy/offline/install.sh": PROJECT_ROOT / "deploy/offline/install.sh",
    "deploy/physical/coordinator-postgres.env.example": (
        PROJECT_ROOT / "deploy/physical/coordinator-postgres.env.example"
    ),
    "LICENSE": PROJECT_ROOT / "LICENSE",
}
SAFE_LABEL_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
SAFE_VERSION_RE = re.compile(r"^v?[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$")
MAX_FILE_BYTES = 20 * 1024 * 1024 * 1024


class OfflineBundleError(ValueError):
    """Offline inputs were incomplete, unsafe, or not release artifacts."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _artifact(value: str) -> tuple[str, Path]:
    label, separator, raw_path = value.partition("=")
    if not separator or not SAFE_LABEL_RE.fullmatch(label):
        raise OfflineBundleError("Artifacts must use safe label=path syntax")
    path = Path(raw_path)
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_file():
        raise OfflineBundleError(f"Artifact {label} must be a regular non-symlink file")
    if resolved.stat().st_size < 1 or resolved.stat().st_size > MAX_FILE_BYTES:
        raise OfflineBundleError(f"Artifact {label} has an invalid size")
    return label, resolved


def _tar_info(name: str, size: int, mode: int = 0o640) -> tarfile.TarInfo:
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts:
        raise OfflineBundleError("Bundle path is unsafe")
    info = tarfile.TarInfo(str(pure))
    info.size = size
    info.mode = mode
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = 0
    return info


def build_bundle(
    *,
    version: str,
    artifacts: dict[str, Path],
    output_path: Path,
) -> dict[str, object]:
    if not SAFE_VERSION_RE.fullmatch(version):
        raise OfflineBundleError("Version must be a semantic release version")
    if set(artifacts) != REQUIRED_ARTIFACTS:
        missing = sorted(REQUIRED_ARTIFACTS - set(artifacts))
        extra = sorted(set(artifacts) - REQUIRED_ARTIFACTS)
        raise OfflineBundleError(f"Offline artifact set mismatch: missing={missing}, extra={extra}")
    for label, path in artifacts.items():
        if path.is_symlink() or not path.resolve().is_file():
            raise OfflineBundleError(
                f"Artifact {label} must be a regular non-symlink file"
            )
        if path.resolve().stat().st_size < 1 or path.resolve().stat().st_size > MAX_FILE_BYTES:
            raise OfflineBundleError(f"Artifact {label} has an invalid size")
    output = output_path.resolve()
    if output_path.is_symlink() or not output.name.endswith(".tar.gz"):
        raise OfflineBundleError("Output must be a non-symlink .tar.gz file")
    output.parent.mkdir(parents=True, exist_ok=True)

    entries: dict[str, Path] = {}
    for label, artifact in artifacts.items():
        entries[f"artifacts/{label}/{artifact.name}"] = artifact
    for name, path in STATIC_FILES.items():
        if path.is_symlink() or not path.is_file():
            raise OfflineBundleError(f"Required static release file is unavailable: {name}")
        entries[name] = path

    files = [
        {
            "path": name,
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
        }
        for name, path in sorted(entries.items())
    ]
    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH", "0")
    if not source_date_epoch.isdigit():
        raise OfflineBundleError("SOURCE_DATE_EPOCH must be a non-negative integer")
    created_at = datetime.fromtimestamp(int(source_date_epoch), UTC)
    manifest = {
        "schema_version": "rarelink-offline-release-manifest-v1",
        "version": version,
        "target_platform": "linux/arm64",
        "created_at_utc": created_at.isoformat().replace("+00:00", "Z"),
        "files": files,
        "image_signature_verification_required_before_export": True,
        "network_required_after_transfer": False,
        "credential_included": False,
        "private_key_included": False,
        "patient_data_included": False,
        "claim_boundary": (
            "The bundle contains release software and OCI/Docker image archives only. "
            "Hospital configuration, certificates, credentials, and patient data are "
            "provisioned separately."
        ),
    }
    manifest_bytes = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    checksums = "".join(
        f"{item['sha256']}  {item['path']}\n" for item in files
    ).encode()

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".rarelink-offline-",
        suffix=".tar.gz",
        dir=output.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with (
            temporary.open("wb") as raw,
            gzip.GzipFile(
                filename="",
                fileobj=raw,
                mode="wb",
                mtime=0,
            ) as compressed,
            tarfile.open(fileobj=compressed, mode="w") as archive,
        ):
            for name, path in sorted(entries.items()):
                mode = 0o750 if name == "deploy/offline/install.sh" else 0o640
                info = _tar_info(name, path.stat().st_size, mode)
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
            archive.addfile(
                _tar_info("release-manifest.json", len(manifest_bytes)),
                io.BytesIO(manifest_bytes),
            )
            archive.addfile(
                _tar_info("SHA256SUMS", len(checksums)),
                io.BytesIO(checksums),
            )
        os.chmod(temporary, 0o640)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "schema_version": "rarelink-offline-release-build-v1",
        "version": version,
        "target_platform": "linux/arm64",
        "bundle_file_name": output.name,
        "bundle_sha256": _sha256(output),
        "file_count": len(entries),
        "credential_included": False,
        "private_key_included": False,
        "patient_data_included": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    parsed = dict(_artifact(item) for item in args.artifact)
    if len(parsed) != len(args.artifact):
        raise SystemExit("Artifact labels must be unique")
    receipt = build_bundle(
        version=args.version,
        artifacts=parsed,
        output_path=args.output,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
