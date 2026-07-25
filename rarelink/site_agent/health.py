"""Safe local health probes that return no paths, hostnames, or patient data."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import os
import shutil
import ssl
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from rarelink.site_agent.config import SiteAgentSettings
from rarelink.site_agent.schemas import CheckResult, HealthSnapshot, utc_now


class HealthProvider(Protocol):
    def __call__(self) -> HealthSnapshot: ...


def _memory_percent_free() -> float:
    total_pages = int(os.sysconf("SC_PHYS_PAGES"))
    available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
    return (available_pages / total_pages * 100) if total_pages else 0.0


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _certificate_check(path: Path | None) -> CheckResult:
    if path is None:
        return CheckResult(ok=False, status="not_configured")
    if not path.is_file():
        return CheckResult(ok=False, status="missing")
    try:
        decoded = ssl._ssl._test_decode_cert(str(path))  # type: ignore[attr-defined]
        expires_at = datetime.strptime(decoded["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=UTC
        )
        fingerprint = _sha256_file(path)
        valid = expires_at > datetime.now(UTC)
        return CheckResult(
            ok=valid,
            status="valid" if valid else "expired",
            details={
                "expires_at": expires_at.isoformat(),
                "certificate_sha256": fingerprint,
                "certificate_subject_exported": False,
            },
        )
    except (KeyError, OSError, ssl.SSLError, ValueError):
        return CheckResult(ok=False, status="invalid")


def _dependency_check(modules: tuple[str, ...]) -> CheckResult:
    versions: dict[str, str] = {}
    missing: list[str] = []
    for module in modules:
        if importlib.util.find_spec(module) is None:
            missing.append(module)
            continue
        try:
            versions[module] = importlib.metadata.version(module)
        except importlib.metadata.PackageNotFoundError:
            versions[module] = "present"
    return CheckResult(
        ok=not missing,
        status="available" if not missing else "missing",
        details={"versions": versions, "missing": missing},
    )


def _gpu_check() -> CheckResult:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return CheckResult(ok=False, status="nvidia_smi_missing")
    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return CheckResult(ok=False, status="probe_failed")
    rows = [row for row in result.stdout.splitlines() if row.strip()]
    return CheckResult(
        ok=result.returncode == 0 and bool(rows),
        status="available" if result.returncode == 0 and rows else "unavailable",
        details={"device_count": len(rows), "device_names_exported": False},
    )


def collect_health(settings: SiteAgentSettings) -> HealthSnapshot:
    settings.artifact_root.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(settings.artifact_root)
    disk_free_percent = disk.free / disk.total * 100 if disk.total else 0
    memory_free_percent = _memory_percent_free()
    manifest_present = settings.dataset_manifest.is_file()
    startup_present = (settings.startup_kit / "startup").is_dir()

    checks = {
        "gpu": _gpu_check(),
        "disk": CheckResult(
            ok=disk_free_percent >= settings.required_free_disk_percent,
            status="sufficient"
            if disk_free_percent >= settings.required_free_disk_percent
            else "insufficient",
            details={"free_percent": round(disk_free_percent, 2)},
        ),
        "memory": CheckResult(
            ok=memory_free_percent >= settings.required_free_memory_percent,
            status="sufficient"
            if memory_free_percent >= settings.required_free_memory_percent
            else "insufficient",
            details={"free_percent": round(memory_free_percent, 2)},
        ),
        "dependencies": _dependency_check(settings.module_names),
        "certificate": _certificate_check(settings.certificate_file),
        "dataset_manifest": CheckResult(
            ok=manifest_present,
            status="present" if manifest_present else "missing",
            details={"local_path_exported": False},
        ),
        "startup_kit": CheckResult(
            ok=startup_present,
            status="present" if startup_present else "missing",
            details={"local_path_exported": False, "private_key_exported": False},
        ),
    }
    return HealthSnapshot(
        ready=all(check.ok for check in checks.values()),
        checked_at=utc_now(),
        checks=checks,
    )
