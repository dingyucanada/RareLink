from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from rarelink.operations.postgres_backup import (
    PostgresRecoveryError,
    create_backup,
    restore_backup,
    verify_backup,
)

REVISION = "20260726_release"


class FakePostgresTools:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command, **_kwargs):  # type: ignore[no-untyped-def]
        self.commands.append(command)
        if command[0] == "psql":
            return subprocess.CompletedProcess(command, 0, f"{REVISION}\n", "")
        if command[0] == "pg_dump":
            output = Path(
                next(
                    item.split("=", 1)[1]
                    for item in command
                    if item.startswith("--file=")
                )
            )
            output.write_bytes(b"PGDMP reviewed backup bytes")
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[0] == "pg_restore":
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "", "unsupported")


def test_postgres_backup_and_restore_drill_are_verified(tmp_path: Path) -> None:
    tools = FakePostgresTools()
    backup = tmp_path / "rarelink.dump"
    service_file = tmp_path / "protected-pg-service.conf"
    service_file.write_text("[rarelink-production]\nhost=postgres\n")
    os.chmod(service_file, 0o600)
    env = {"PGSERVICEFILE": str(service_file)}

    manifest = create_backup(
        service="rarelink-production",
        output_path=backup,
        expected_revision=REVISION,
        runner=tools,
        environ=env,
    )
    receipt = restore_backup(
        backup_path=backup,
        manifest_path=backup.with_suffix(".manifest.json"),
        target_service="rarelink-restore-verify",
        confirmed_target_service="rarelink-restore-verify",
        expected_revision=REVISION,
        runner=tools,
        environ=env,
    )

    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert manifest["credential_exported"] is False
    assert manifest["connection_string_exported"] is False
    assert "rarelink-production" not in backup.with_suffix(".manifest.json").read_text()
    assert receipt["verified"] is True
    assert any(command[0] == "pg_dump" for command in tools.commands)
    assert any(command[0] == "pg_restore" for command in tools.commands)
    assert not any("password" in " ".join(command).lower() for command in tools.commands)


def test_postgres_restore_rejects_tamper_and_wrong_confirmation(tmp_path: Path) -> None:
    tools = FakePostgresTools()
    backup = tmp_path / "rarelink.dump"
    service_file = tmp_path / "pg.conf"
    service_file.write_text("[rarelink-production]\nhost=postgres\n")
    os.chmod(service_file, 0o600)
    env = {"PGSERVICEFILE": str(service_file)}
    create_backup(
        service="rarelink-production",
        output_path=backup,
        expected_revision=REVISION,
        runner=tools,
        environ=env,
    )

    with pytest.raises(PostgresRecoveryError, match="confirmation"):
        restore_backup(
            backup_path=backup,
            manifest_path=backup.with_suffix(".manifest.json"),
            target_service="rarelink-restore-verify",
            confirmed_target_service="wrong-target",
            expected_revision=REVISION,
            runner=tools,
            environ=env,
        )

    backup.write_bytes(backup.read_bytes() + b"tampered")
    os.chmod(backup, 0o600)
    with pytest.raises(PostgresRecoveryError, match="binding"):
        verify_backup(
            backup_path=backup,
            manifest_path=backup.with_suffix(".manifest.json"),
            expected_revision=REVISION,
        )


def test_postgres_backup_requires_protected_service_configuration(tmp_path: Path) -> None:
    with pytest.raises(PostgresRecoveryError, match="PGSERVICEFILE"):
        create_backup(
            service="rarelink-production",
            output_path=tmp_path / "rarelink.dump",
            expected_revision=REVISION,
            runner=FakePostgresTools(),
            environ={},
        )
