"""PostgreSQL custom-format backup and verified restore drill primitives."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SAFE_SERVICE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,62}[A-Za-z0-9]$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_BACKUP_BYTES = 2 * 1024 * 1024 * 1024 * 1024
Runner = Callable[..., subprocess.CompletedProcess[str]]


class PostgresRecoveryError(RuntimeError):
    """A backup or restore operation violated the reviewed recovery contract."""


def _service(value: str, label: str) -> str:
    if not SAFE_SERVICE_RE.fullmatch(value):
        raise PostgresRecoveryError(f"{label} must be a safe pg_service name")
    return value


def _regular_output(path: Path, suffix: str) -> Path:
    if path.is_symlink() or path.suffix != suffix:
        raise PostgresRecoveryError(f"Output must be a non-symlink {suffix} file")
    output = path.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def _run(
    runner: Runner,
    command: Sequence[str],
    *,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(
            list(command),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise PostgresRecoveryError(f"{command[0]} is unavailable") from exc
    if result.returncode != 0:
        raise PostgresRecoveryError(f"{command[0]} failed with exit code {result.returncode}")
    return result


def _validate_service_file(env: dict[str, str]) -> None:
    raw_path = env.get("PGSERVICEFILE", "")
    if not raw_path:
        raise PostgresRecoveryError("PGSERVICEFILE must identify a protected service file")
    path = Path(raw_path)
    if path.is_symlink() or not path.resolve().is_file():
        raise PostgresRecoveryError("PGSERVICEFILE must be a regular non-symlink file")
    if stat.S_IMODE(path.resolve().stat().st_mode) & 0o077:
        raise PostgresRecoveryError("PGSERVICEFILE permissions must be 0600 or stricter")


def _revision(runner: Runner, service: str, env: dict[str, str]) -> str:
    result = _run(
        runner,
        [
            "psql",
            f"service={service}",
            "--no-psqlrc",
            "--tuples-only",
            "--no-align",
            "--command",
            "SELECT version_num FROM alembic_version",
        ],
        env=env,
    )
    values = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(values) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", values[0]):
        raise PostgresRecoveryError("Database did not return one safe Alembic revision")
    return values[0]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def create_backup(
    *,
    service: str,
    output_path: Path,
    expected_revision: str,
    runner: Runner = subprocess.run,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create an atomic pg_dump custom archive and a patient-free manifest."""
    service = _service(service, "Source service")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", expected_revision):
        raise PostgresRecoveryError("Expected Alembic revision is invalid")
    output = _regular_output(output_path, ".dump")
    env = dict(os.environ if environ is None else environ)
    _validate_service_file(env)
    if _revision(runner, service, env) != expected_revision:
        raise PostgresRecoveryError("Source database Alembic revision does not match release")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".rarelink-backup-",
        suffix=".dump",
        dir=output.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    os.chmod(temporary, 0o600)
    try:
        _run(
            runner,
            [
                "pg_dump",
                f"--dbname=service={service}",
                "--format=custom",
                "--compress=9",
                "--no-owner",
                "--no-privileges",
                f"--file={temporary}",
            ],
            env=env,
        )
        if not temporary.is_file() or temporary.stat().st_size < 1:
            raise PostgresRecoveryError("pg_dump did not produce a backup archive")
        if temporary.stat().st_size > MAX_BACKUP_BYTES:
            raise PostgresRecoveryError("Backup archive exceeds the safety limit")
        digest = _sha256_file(temporary)
        os.replace(temporary, output)
        os.chmod(output, 0o600)
    finally:
        temporary.unlink(missing_ok=True)

    manifest = {
        "schema_version": "rarelink-postgres-backup-manifest-v1",
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "backup_file_name": output.name,
        "backup_sha256": digest,
        "size_bytes": output.stat().st_size,
        "alembic_revision": expected_revision,
        "source_service_sha256": hashlib.sha256(service.encode()).hexdigest(),
        "format": "postgresql-custom",
        "owner_acl_exported": False,
        "credential_exported": False,
        "connection_string_exported": False,
        "patient_data_classification": "CONTROL_PLANE_DATABASE_MAY_CONTAIN_RESEARCH_METADATA",
    }
    manifest_path = output.with_suffix(".manifest.json")
    if manifest_path.is_symlink():
        raise PostgresRecoveryError("Backup manifest path must not be a symlink")
    temporary_manifest = manifest_path.with_name(f".{manifest_path.name}.tmp")
    temporary_manifest.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary_manifest, 0o600)
    os.replace(temporary_manifest, manifest_path)
    return manifest


def verify_backup(
    *,
    backup_path: Path,
    manifest_path: Path,
    expected_revision: str,
) -> dict[str, Any]:
    if backup_path.is_symlink() or manifest_path.is_symlink():
        raise PostgresRecoveryError("Backup inputs must not be symlinks")
    backup = backup_path.resolve()
    manifest_file = manifest_path.resolve()
    if not backup.is_file() or not manifest_file.is_file():
        raise PostgresRecoveryError("Backup archive and manifest must both exist")
    if stat.S_IMODE(backup.stat().st_mode) & 0o077:
        raise PostgresRecoveryError("Backup archive permissions must be 0600 or stricter")
    if stat.S_IMODE(manifest_file.stat().st_mode) & 0o077:
        raise PostgresRecoveryError("Backup manifest permissions must be 0600 or stricter")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PostgresRecoveryError("Backup manifest is invalid") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "rarelink-postgres-backup-manifest-v1"
        or manifest.get("backup_file_name") != backup.name
        or manifest.get("alembic_revision") != expected_revision
        or manifest.get("size_bytes") != backup.stat().st_size
        or not SHA256_RE.fullmatch(str(manifest.get("backup_sha256", "")))
        or manifest.get("backup_sha256") != _sha256_file(backup)
        or manifest.get("credential_exported") is not False
        or manifest.get("connection_string_exported") is not False
    ):
        raise PostgresRecoveryError("Backup manifest binding failed")
    return manifest


def restore_backup(
    *,
    backup_path: Path,
    manifest_path: Path,
    target_service: str,
    confirmed_target_service: str,
    expected_revision: str,
    runner: Runner = subprocess.run,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Restore only after an exact target-name confirmation and verify revision."""
    target_service = _service(target_service, "Target service")
    if confirmed_target_service != target_service:
        raise PostgresRecoveryError("Restore target confirmation does not match")
    manifest = verify_backup(
        backup_path=backup_path,
        manifest_path=manifest_path,
        expected_revision=expected_revision,
    )
    env = dict(os.environ if environ is None else environ)
    _validate_service_file(env)
    _run(
        runner,
        [
            "pg_restore",
            f"--dbname=service={target_service}",
            "--exit-on-error",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            str(backup_path.resolve()),
        ],
        env=env,
    )
    restored_revision = _revision(runner, target_service, env)
    if restored_revision != expected_revision:
        raise PostgresRecoveryError("Restored database revision does not match release")
    return {
        "schema_version": "rarelink-postgres-restore-receipt-v1",
        "restored_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "backup_sha256": manifest["backup_sha256"],
        "alembic_revision": restored_revision,
        "target_service_sha256": hashlib.sha256(target_service.encode()).hexdigest(),
        "verified": True,
        "credential_exported": False,
        "connection_string_exported": False,
    }
