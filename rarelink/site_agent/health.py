"""Safe local health probes that return no paths, hostnames, or patient data."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Protocol

from rarelink.site_agent.config import SiteAgentSettings
from rarelink.site_agent.pki import validate_public_certificate
from rarelink.site_agent.schemas import CheckResult, HealthSnapshot, utc_now
from rarelink.site_data import DatasetValidationError, verify_site_dataset_receipt

REQUIRED_PREFLIGHT_CHECKS = frozenset(
    {
        "gpu",
        "disk",
        "memory",
        "cpu",
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
    expected_identity: str = "hospital-a",
    ca_bundle: Path | None = None,
    require_chain: bool = False,
    crl_file: Path | None = None,
    require_crl: bool = False,
    now: datetime | None = None,
) -> CheckResult:
    return validate_public_certificate(
        certificate_path=path,
        startup_kit=startup_kit,
        expected_identity=expected_identity,
        minimum_valid_days=minimum_valid_days,
        restrict_to_startup_kit=restrict_to_startup_kit,
        ca_bundle=ca_bundle,
        require_chain=require_chain,
        crl_file=crl_file,
        require_crl=require_crl,
        now=now,
    )


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
    contract = {
        "required_modules": sorted(modules),
        "versions": {name: versions[name] for name in sorted(versions)},
        "missing": sorted(missing),
    }
    return CheckResult(
        ok=not missing,
        status="available" if not missing else "missing",
        details={
            **contract,
            "dependency_contract_sha256": hashlib.sha256(
                json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        },
    )


def _cuda_version(executable: str) -> str:
    try:
        result = subprocess.run(
            [executable],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    matched = re.search(r"CUDA Version:\s*([0-9.]+)", result.stdout)
    return matched.group(1) if matched else "unknown"


def _gpu_check(
    required_free_memory_mib: int,
    maximum_temperature_c: int = 85,
) -> CheckResult:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return CheckResult(ok=False, status="nvidia_smi_missing")
    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=name,driver_version,memory.total,memory.free,temperature.gpu",
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
    parsed: list[dict[str, object]] = []
    try:
        for row in rows:
            name, driver, total_text, free_text, temperature_text = [
                item.strip() for item in row.split(",", maxsplit=4)
            ]
            temperature = (
                None if temperature_text in {"N/A", "[N/A]"} else int(temperature_text)
            )
            parsed.append(
                {
                    "name": name,
                    "driver_version": driver,
                    "total_memory_mib": int(total_text),
                    "free_memory_mib": int(free_text),
                    "temperature_c": temperature,
                }
            )
    except (TypeError, ValueError):
        return CheckResult(ok=False, status="probe_output_invalid")
    eligible = [
        item
        for item in parsed
        if int(item["free_memory_mib"]) >= required_free_memory_mib
    ]
    measured_temperatures = [
        int(item["temperature_c"])
        for item in parsed
        if item["temperature_c"] is not None
    ]
    temperature_ok = all(
        temperature <= maximum_temperature_c for temperature in measured_temperatures
    )
    available = (
        result.returncode == 0
        and bool(parsed)
        and bool(eligible)
        and temperature_ok
    )
    if result.returncode != 0 or not parsed:
        status = "unavailable"
    elif not eligible:
        status = "insufficient_free_memory"
    elif not temperature_ok:
        status = "temperature_exceeded"
    else:
        status = "available"
    return CheckResult(
        ok=available,
        status=status,
        details={
            "device_count": len(parsed),
            "eligible_device_count": len(eligible),
            "minimum_required_free_memory_mib": required_free_memory_mib,
            "maximum_free_memory_mib": max(
                (int(item["free_memory_mib"]) for item in parsed), default=0
            ),
            "maximum_temperature_c": maximum_temperature_c,
            "temperature_available": bool(measured_temperatures),
            "cuda_version": _cuda_version(executable),
            "devices": parsed,
            "device_uuid_exported": False,
            "device_serial_exported": False,
        },
    )


def _cpu_check(maximum_load_percent: float) -> CheckResult:
    try:
        load_1, load_5, load_15 = os.getloadavg()
        cpu_count = os.cpu_count() or 1
        normalized = load_1 / cpu_count * 100
    except (OSError, ValueError):
        return CheckResult(ok=False, status="probe_failed")
    return CheckResult(
        ok=normalized <= maximum_load_percent,
        status="sufficient" if normalized <= maximum_load_percent else "load_exceeded",
        details={
            "logical_cpu_count": cpu_count,
            "load_average_1m": round(load_1, 3),
            "load_average_5m": round(load_5, 3),
            "load_average_15m": round(load_15, 3),
            "normalized_load_percent": round(normalized, 2),
            "maximum_load_percent": maximum_load_percent,
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
        "gpu": _gpu_check(
            settings.required_gpu_free_memory_mib,
            settings.maximum_gpu_temperature_c,
        ),
        "disk": disk_status,
        "memory": memory_status,
        "cpu": _cpu_check(settings.maximum_cpu_load_percent),
        "dependencies": _dependency_check(settings.module_names),
        "certificate": _certificate_check(
            settings.certificate_file,
            startup_kit=settings.startup_kit,
            minimum_valid_days=settings.certificate_min_valid_days,
            restrict_to_startup_kit=settings.require_certificate_under_startup_kit,
            expected_identity=settings.certificate_expected_identity or settings.site_id,
            ca_bundle=settings.certificate_ca_bundle,
            require_chain=settings.require_certificate_chain,
            crl_file=settings.certificate_crl_file,
            require_crl=settings.require_certificate_crl,
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
