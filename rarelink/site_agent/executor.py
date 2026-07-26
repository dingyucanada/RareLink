"""Injectable boundary between the control protocol and NVFLARE execution."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from typing import Protocol

from rarelink.site_agent.config import SiteAgentSettings
from rarelink.site_agent.schemas import TaskRecord


class SiteTaskExecutor(Protocol):
    def start(self, task: TaskRecord) -> str | None: ...

    def stop(self, task: TaskRecord) -> str | None: ...

    def recover(self, task: TaskRecord) -> str | None: ...


class DisabledExecutor:
    """Safe default: the agent cannot claim training without a real adapter."""

    def _unavailable(self) -> None:
        raise RuntimeError("site_task_executor_not_configured")

    def start(self, task: TaskRecord) -> str | None:
        self._unavailable()

    def stop(self, task: TaskRecord) -> str | None:
        self._unavailable()

    def recover(self, task: TaskRecord) -> str | None:
        self._unavailable()

    def is_running(self, task: TaskRecord) -> bool:
        return False


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


class SystemdServiceExecutor:
    """Control one pre-authorized FLARE Client service without a shell.

    The unit name comes from validated startup configuration, never from an API
    request. Raw systemctl output is intentionally discarded so local paths,
    account names, or administrator diagnostics cannot enter a task receipt.
    """

    def __init__(
        self,
        service_name: str,
        runner: CommandRunner = _run_command,
    ) -> None:
        self.service_name = service_name
        self._runner = runner

    def _action(self, action: str) -> str:
        result = self._runner(("systemctl", action, self.service_name))
        if result.returncode:
            raise RuntimeError("nvflare_service_action_failed")
        return f"systemd:{self.service_name}"

    def start(self, task: TaskRecord) -> str:
        return self._action("start")

    def stop(self, task: TaskRecord) -> str:
        return self._action("stop")

    def recover(self, task: TaskRecord) -> str:
        return self._action("restart")

    def is_running(self, task: TaskRecord) -> bool:
        result = self._runner(("systemctl", "is-active", "--quiet", self.service_name))
        return result.returncode == 0


def build_site_executor(settings: SiteAgentSettings) -> SiteTaskExecutor:
    if settings.executor_backend == "systemd":
        return SystemdServiceExecutor(settings.nvflare_service_name)
    return DisabledExecutor()
