#!/usr/bin/env python3
"""Fail-closed static contract for RareLink release engineering assets."""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ReleaseEngineeringError(ValueError):
    """Release automation is incomplete or has lost a mandatory security gate."""


def _text(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def _require(content: str, markers: set[str], label: str) -> None:
    missing = sorted(marker for marker in markers if marker not in content)
    if missing:
        raise ReleaseEngineeringError(f"{label} is missing required markers: {missing}")


def validate_release_engineering() -> dict[str, object]:
    ci = _text(".github/workflows/ci.yml")
    release = _text(".github/workflows/release.yml")
    spark = _text(".github/workflows/spark-arm64.yml")
    coordinator = _text("deploy/Dockerfile.coordinator")
    web = _text("deploy/Dockerfile.web.production")
    dockerignore = _text(".dockerignore")
    offline = _text("scripts/build_offline_release_bundle.py")
    backup = _text("rarelink/operations/postgres_backup.py")
    observability = _text("rarelink/observability.py")
    contract = json.loads(_text("deploy/release/arm64-build-contract.json"))

    _require(
        ci,
        {
            "python -m pytest -q",
            "python -m ruff check",
            "python -m pip_audit",
            "npm --prefix apps/web audit --audit-level=high",
            "platforms: linux/amd64,linux/arm64",
            "deploy/Dockerfile.coordinator",
            "deploy/Dockerfile.web.production",
        },
        "CI workflow",
    )
    _require(
        release,
        {
            "permissions:",
            "id-token: write",
            "packages: write",
            "cosign sign --yes",
            "cosign verify",
            "actions/attest-build-provenance@v2",
            "syft ",
            "aquasecurity/trivy-action",
            "platforms: linux/amd64,linux/arm64",
            "crane pull --platform linux/arm64",
            "build_offline_release_bundle.py",
            "gh release create",
            "PACKAGE_VERSION",
        },
        "Release workflow",
    )
    _require(
        spark,
        {
            "runs-on: [self-hosted, linux, ARM64, dgx-spark]",
            'test "$(uname -m)" = "aarch64"',
            "cosign sign --yes",
            "cosign verify",
            "syft ",
            "actions/attest-build-provenance@v2",
        },
        "Native Spark workflow",
    )
    for dockerfile, label in ((coordinator, "coordinator"), (web, "web")):
        _require(
            dockerfile,
            {"USER ", "org.opencontainers.image" if label == "coordinator" else "EXPOSE 8080"},
            f"{label} production Dockerfile",
        )
    _require(
        dockerignore,
        {".env", ".venv", "artifacts", "data/raw", "outputs", "*.pt"},
        "Docker build-context boundary",
    )
    if contract.get("schema_version") != "rarelink-arm64-build-contract-v1":
        raise ReleaseEngineeringError("ARM64 build contract schema is invalid")
    if contract.get("required_platforms") != ["linux/amd64", "linux/arm64"]:
        raise ReleaseEngineeringError("ARM64 build contract lost a required platform")
    requirements = contract.get("release_requirements")
    if not isinstance(requirements, dict) or not all(requirements.values()):
        raise ReleaseEngineeringError("ARM64 release requirements must all be enabled")
    _require(
        offline,
        {
            "REQUIRED_ARTIFACTS",
            "coordinator-arm64-image",
            "vulnerability-report",
            "SHA256SUMS",
            "credential_included",
        },
        "Offline bundle builder",
    )
    _require(
        backup,
        {
            "pg_dump",
            "pg_restore",
            "PGSERVICEFILE",
            "confirmed_target_service",
            "backup_sha256",
        },
        "PostgreSQL recovery implementation",
    )
    _require(
        observability,
        {
            "prometheus_client",
            "OTLPSpanExporter",
            "http.route",
            "rarelink_metrics_bearer_token",
        },
        "Observability implementation",
    )
    return {
        "schema_version": "rarelink-release-engineering-validation-v1",
        "github_actions": True,
        "automated_release": True,
        "sbom": True,
        "container_signing": "keyless-cosign",
        "vulnerability_scanning": True,
        "multi_arch": ["linux/amd64", "linux/arm64"],
        "native_spark_arm64_contract": True,
        "offline_arm64_bundle": True,
        "postgres_backup_restore": True,
        "prometheus": True,
        "opentelemetry": True,
        "validated": True,
    }


def main() -> int:
    print(json.dumps(validate_release_engineering(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
