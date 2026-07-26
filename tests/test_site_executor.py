import subprocess

import pytest

from rarelink.site_agent.config import SiteAgentSettings
from rarelink.site_agent.executor import (
    DisabledExecutor,
    SystemdServiceExecutor,
    build_site_executor,
)


def test_systemd_executor_uses_only_fixed_service_and_allowlisted_actions() -> None:
    commands: list[list[str]] = []

    def runner(command):  # type: ignore[no-untyped-def]
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    executor = SystemdServiceExecutor(
        "rarelink-flare-client.service",
        runner=runner,
    )

    assert executor.start(None) == "systemd:rarelink-flare-client.service"  # type: ignore[arg-type]
    assert executor.stop(None) == "systemd:rarelink-flare-client.service"  # type: ignore[arg-type]
    assert executor.recover(None) == "systemd:rarelink-flare-client.service"  # type: ignore[arg-type]
    assert executor.is_running(None) is True  # type: ignore[arg-type]
    assert commands == [
        ["systemctl", "start", "rarelink-flare-client.service"],
        ["systemctl", "stop", "rarelink-flare-client.service"],
        ["systemctl", "restart", "rarelink-flare-client.service"],
        ["systemctl", "is-active", "--quiet", "rarelink-flare-client.service"],
    ]


def test_systemd_executor_discards_sensitive_command_output() -> None:
    def runner(command):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            command,
            1,
            "",
            "patient_name=hidden password=secret /private/path",
        )

    executor = SystemdServiceExecutor("rarelink-flare-client.service", runner=runner)
    with pytest.raises(RuntimeError) as captured:
        executor.start(None)  # type: ignore[arg-type]

    message = str(captured.value)
    assert "patient_name" not in message
    assert "password" not in message
    assert "/private/path" not in message


def test_executor_backend_is_disabled_by_default_and_service_name_is_validated(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    common = {
        "_env_file": None,
        "site_id": "hospital-a",
        "dataset_manifest": tmp_path / "manifest.json",
        "artifact_root": tmp_path / "artifacts",
        "startup_kit": tmp_path / "startup-kit",
        "state_database": tmp_path / "state.sqlite3",
        "api_token": "site-agent-test-token-000000",
        "receipt_hmac_key": "site-agent-test-hmac-key-000000000000",
    }
    settings = SiteAgentSettings(**common)

    assert isinstance(build_site_executor(settings), DisabledExecutor)
    with pytest.raises(ValueError, match="systemd"):
        SiteAgentSettings(
            **common,
            executor_backend="systemd",
            nvflare_service_name="../../unsafe;command",
        )
