from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path

import pytest

from scripts.build_offline_release_bundle import (
    REQUIRED_ARTIFACTS,
    OfflineBundleError,
    build_bundle,
)


def artifacts(tmp_path: Path) -> dict[str, Path]:
    values: dict[str, Path] = {}
    for index, label in enumerate(sorted(REQUIRED_ARTIFACTS), start=1):
        suffix = ".whl" if label == "python-wheel" else ".tar"
        if label in {"python-sdist", "vulnerability-report"}:
            suffix = ".tar.gz"
        if label.endswith("sbom"):
            suffix = ".spdx.json"
        path = tmp_path / f"{label}{suffix}"
        path.write_bytes(f"reviewed-artifact-{index}".encode())
        values[label] = path
    return values


def test_offline_arm64_bundle_is_complete_and_reproducible(tmp_path: Path) -> None:
    inputs = artifacts(tmp_path)
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"

    first_receipt = build_bundle(
        version="v0.2.0",
        artifacts=inputs,
        output_path=first,
    )
    build_bundle(
        version="v0.2.0",
        artifacts=inputs,
        output_path=second,
    )

    assert first_receipt["target_platform"] == "linux/arm64"
    assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(
        second.read_bytes()
    ).digest()
    with tarfile.open(first) as archive:
        names = set(archive.getnames())
        assert "release-manifest.json" in names
        assert "SHA256SUMS" in names
        assert "deploy/offline/install.sh" in names
        manifest_member = archive.extractfile("release-manifest.json")
        assert manifest_member is not None
        manifest = json.load(manifest_member)
        assert manifest["credential_included"] is False
        assert manifest["private_key_included"] is False
        assert manifest["patient_data_included"] is False


def test_offline_bundle_rejects_missing_artifact_or_symlink(tmp_path: Path) -> None:
    inputs = artifacts(tmp_path)
    inputs.pop("coordinator-sbom")
    with pytest.raises(OfflineBundleError, match="mismatch"):
        build_bundle(
            version="v0.2.0",
            artifacts=inputs,
            output_path=tmp_path / "missing.tar.gz",
        )

    inputs = artifacts(tmp_path)
    target = inputs["web-sbom"]
    link = tmp_path / "linked.spdx.json"
    link.symlink_to(target)
    inputs["web-sbom"] = link
    with pytest.raises(OfflineBundleError, match="static|artifact|symlink"):
        build_bundle(
            version="v0.2.0",
            artifacts=inputs,
            output_path=tmp_path / "unsafe.tar.gz",
        )
