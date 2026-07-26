"""Safe local health probes that return no paths, hostnames, or patient data."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import shutil
import ssl
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from rarelink.site_agent.config import SiteAgentSettings
from rarelink.site_agent.schemas import CheckResult, HealthSnapshot, utc_now
from rarelink.site_data import DatasetValidationError, verify_site_dataset_receipt

REQUIRED_PREFLIGHT_CHECKS = frozenset(
    {
        "gpu",
        "disk",
        "memory",
        "dependencies",
        "certificate",
        "dataset_manifest",
        "startup_kit",
    }
)


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


def _path_permissions_secure(path: Path, allowed_root: Path) -> bool:
    """Inspect metadata only; never open a private key or traverse unrelated paths."""
    try:
        current_input = path
        while True:
            if current_input.is_symlink():
                return False
            if current_input == allowed_root:
                break
            if current_input.parent == current_input:
                return False
            current_input = current_input.parent
        if allowed_root.is_symlink():
            return False
        resolved_path = path.resolve(strict=True)
        resolved_root = allowed_root.resolve(strict=True)
        if not resolved_path.is_relative_to(resolved_root):
            return False
        current = resolved_path
        while True:
            mode = current.stat().st_mode
            if mode & (stat.S_IWGRP | stat.S_IWOTH):
                return False
            if current == resolved_root:
                break
            current = current.parent
        return True
    except OSError:
        return False


def health_is_ready(snapshot: HealthSnapshot) -> bool:
    """Reject incomplete or internally inconsistent injected health evidence."""
    return (
        snapshot.ready
        and REQUIRED_PREFLIGHT_CHECKS.issubset(snapshot.checks)
        and all(snapshot.checks[name].ok for name in REQUIRED_PREFLIGHT_CHECKS)
    )


def _certificate_check(
    path: Path | None,
    *,
    startup_kit: Path,
    minimum_valid_days: int,
    restrict_to_startup_kit: bool,
    now: datetime | None = None,
) -> CheckResult:
    if path is None:
        return CheckResult(ok=False, status="not_configured")
    if path.is_symlink():
        return CheckResult(ok=False, status="symlink_rejected")
    if not path.is_file():
        return CheckResult(ok=False, status="missing")
    permission_root = startup_kit if restrict_to_startup_kit else path.parent
    if not _path_permissions_secure(path, permission_root):
        return CheckResult(
            ok=False,
            status="insecure_path_permissions",
            details={
                "certificate_content_exported": False,
                "private_key_content_read": False,
                "local_path_exported": False,
            },
        )
    try:
        decoded = ssl._ssl._test_decode_cert(str(path))  # type: ignore[attr-defined]
        valid_from = datetime.strptime(decoded["notBefore"], "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=UTC
        )
        expires_at = datetime.strptime(decoded["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=UTC
        )
        fingerprint = _sha256_file(path)
        observed_at = now or datetime.now(UTC)
        seconds_remaining = (expires_at - observed_at).total_seconds()
        minimum_seconds = minimum_valid_days * 86_400
        if valid_from > observed_at:
            status = "not_yet_valid"
            valid = False
        elif seconds_remaining <= 0:
            status = "expired"
            valid = False
        elif seconds_remaining < minimum_seconds:
            status = "expiring_soon"
            valid = False
        else:
            status = "valid"
            valid = True
        return CheckResult(
            ok=valid,
            status=status,
            details={
                "valid_from": valid_from.isoformat(),
                "expires_at": expires_at.isoformat(),
                "minimum_valid_days": minimum_valid_days,
                "certificate_sha256": fingerprint,
                "certificate_subject_exported": False,
                "certificate_content_exported": False,
                "private_key_content_read": False,
                "local_path_exported": False,
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


def _gpu_check(required_free_memory_mib: int) -> CheckResult:
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
    rows = [row.strip() for row in result.stdout.splitlines() if row.strip()]
    parsed: list[tuple[int, int]] = []
    try:
        for row in rows:
            total_text, free_text = [item.strip() for item in row.split(",", maxsplit=1)]
            parsed.append((int(total_text), int(free_text)))
    except (TypeError, ValueError):
        return CheckResult(ok=False, status="probe_output_invalid")
    eligible = [item for item in parsed if item[1] >= required_free_memory_mib]
    available = result.returncode == 0 and bool(parsed) and bool(eligible)
    return CheckResult(
        ok=available,
        status="available" if available else "insufficient_free_memory",
        details={
            "device_count": len(parsed),
            "eligible_device_count": len(eligible),
            "minimum_required_free_memory_mib": required_free_memory_mib,
            "maximum_free_memory_mib": max((item[1] for item in parsed), default=0),
            "device_names_exported": False,
        },
    )


def _dataset_check(settings: SiteAgentSettings) -> CheckResult:
    if not settings.dataset_manifest.is_file():
        return CheckResult(ok=False, status="manifest_missing")
    if not settings.require_dataset_receipt:
        return CheckResult(
            ok=True,
            status="manifest_present_receipt_not_required",
            details={
                "local_path_exported": False,
                "dataset_receipt_verified": False,
            },
        )
    receipt_path = settings.dataset_receipt
    if receipt_path is None or not receipt_path.is_file() or receipt_path.is_symlink():
        return CheckResult(ok=False, status="receipt_missing")
    try:
        receipt = verify_site_dataset_receipt(
            receipt_path,
            settings.dataset_manifest,
            site_id=settings.site_id,
            data_root=settings.dataset_root,
        )
    except (
        DatasetValidationError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return CheckResult(ok=False, status="receipt_or_dataset_invalid")
    return CheckResult(
        ok=True,
        status="receipt_verified",
        details={
            "dataset_receipt_verified": True,
            "dataset_fingerprint": receipt.get("dataset_fingerprint"),
            "receipt_sha256": _sha256_file(receipt_path),
            "case_count": receipt.get("case_count"),
            "local_path_exported": False,
            "case_identifiers_exported": False,
        },
    )


def collect_health(settings: SiteAgentSettings) -> HealthSnapshot:
    try:
        settings.artifact_root.mkdir(parents=True, exist_ok=True)
        disk = shutil.disk_usage(settings.artifact_root)
        disk_free_percent = disk.free / disk.total * 100 if disk.total else 0
        disk_status = CheckResult(
            ok=disk_free_percent >= settings.required_free_disk_percent,
            status="sufficient"
            if disk_free_percent >= settings.required_free_disk_percent
            else "insufficient",
            details={"free_percent": round(disk_free_percent, 2)},
        )
    except OSError:
        disk_status = CheckResult(ok=False, status="probe_failed")
    try:
        memory_free_percent = _memory_percent_free()
        memory_status = CheckResult(
            ok=memory_free_percent >= settings.required_free_memory_percent,
            status="sufficient"
            if memory_free_percent >= settings.required_free_memory_percent
            else "insufficient",
            details={"free_percent": round(memory_free_percent, 2)},
        )
    except (OSError, ValueError):
        memory_status = CheckResult(ok=False, status="probe_failed")
    startup_present = (settings.startup_kit / "startup").is_dir()

    checks = {
        "gpu": _gpu_check(settings.required_gpu_free_memory_mib),
        "disk": disk_status,
        "memory": memory_status,
        "dependencies": _dependency_check(settings.module_names),
        "certificate": _certificate_check(
            settings.certificate_file,
            startup_kit=settings.startup_kit,
            minimum_valid_days=settings.certificate_min_valid_days,
            restrict_to_startup_kit=settings.require_certificate_under_startup_kit,
        ),
        "dataset_manifest": _dataset_check(settings),
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
