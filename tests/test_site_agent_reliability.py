from __future__ import annotations

import os
import subprocess
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

from rarelink.site_agent import SiteAgentSettings, create_site_agent_app
from rarelink.site_agent.forwarder import BackoffPolicy, HeartbeatOutbox
from rarelink.site_agent.health import _certificate_check, _gpu_check
from rarelink.site_agent.schemas import CheckResult, HealthSnapshot, TaskRecord, utc_now
from rarelink.site_agent.store import TaskStore
from scripts import push_site_heartbeat

TOKEN = "site-agent-reliability-token-000000"
HMAC_KEY = "site-agent-reliability-hmac-key-000000000"
CONTRACT = "c" * 64


class RestartAwareExecutor:
    def __init__(self, running_after_restart: bool = True) -> None:
        self.running_after_restart = running_after_restart
        self.calls: list[str] = []

    def start(self, task: TaskRecord) -> str:
        self.calls.append("start")
        return "nvflare-job-reliability"

    def stop(self, task: TaskRecord) -> str:
        self.calls.append("stop")
        return "nvflare-job-reliability"

    def recover(self, task: TaskRecord) -> str:
        self.calls.append("recover")
        return "nvflare-job-reliability"

    def is_running(self, task: TaskRecord) -> bool:
        return self.running_after_restart


def settings(tmp_path: Path) -> SiteAgentSettings:
    manifest = tmp_path / "site" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"cases":[]}', encoding="utf-8")
    startup = tmp_path / "site" / "startup-kit"
    (startup / "startup").mkdir(parents=True)
    return SiteAgentSettings(
        _env_file=None,
        site_id="hospital-a",
        dataset_manifest=manifest,
        artifact_root=tmp_path / "artifacts",
        startup_kit=startup,
        state_database=tmp_path / "site-agent.sqlite3",
        api_token=TOKEN,
        receipt_hmac_key=HMAC_KEY,
        required_modules="",
    )


def snapshot(*, ready: bool, failed_check: str | None = None) -> HealthSnapshot:
    checks = {
        "gpu": CheckResult(ok=True, status="available"),
        "disk": CheckResult(ok=True, status="sufficient"),
        "memory": CheckResult(ok=True, status="sufficient"),
        "cpu": CheckResult(ok=True, status="sufficient"),
        "certificate": CheckResult(ok=True, status="valid"),
        "dependencies": CheckResult(ok=True, status="available"),
        "dataset_manifest": CheckResult(ok=True, status="receipt_verified"),
        "startup_kit": CheckResult(ok=True, status="present"),
    }
    if failed_check:
        checks[failed_check] = CheckResult(ok=False, status="preflight_failure")
    return HealthSnapshot(ready=ready, checked_at=utc_now(), checks=checks)


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def write_certificate(
    path: Path,
    *,
    valid_from: datetime,
    valid_until: datetime,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "hospital-a")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(valid_from)
        .not_valid_after(valid_until)
        .sign(private_key, hashes.SHA256())
    )
    path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    path.chmod(0o600)


def test_certificate_validity_window_and_permissions_fail_closed(tmp_path: Path) -> None:
    observed_at = datetime.now(UTC).replace(microsecond=0)
    startup = tmp_path / "startup-kit"
    startup.mkdir(mode=0o700)
    certificate = startup / "client.crt"
    write_certificate(
        certificate,
        valid_from=observed_at - timedelta(days=1),
        valid_until=observed_at + timedelta(days=60),
    )

    valid = _certificate_check(
        certificate,
        startup_kit=startup,
        minimum_valid_days=14,
        restrict_to_startup_kit=True,
        now=observed_at,
    )
    assert valid.ok is True
    assert valid.status == "valid"
    assert valid.details["private_key_content_read"] is False
    assert str(certificate) not in str(valid.model_dump())

    certificate.chmod(0o660)
    insecure = _certificate_check(
        certificate,
        startup_kit=startup,
        minimum_valid_days=14,
        restrict_to_startup_kit=True,
        now=observed_at,
    )
    assert insecure.ok is False
    assert insecure.status == "insecure_path_permissions"


@pytest.mark.parametrize(
    ("valid_from_delta", "valid_until_delta", "expected"),
    [
        (timedelta(days=1), timedelta(days=60), "not_yet_valid"),
        (-timedelta(days=1), timedelta(days=2), "expiring_soon"),
        (-timedelta(days=60), -timedelta(seconds=1), "expired"),
    ],
)
def test_certificate_time_failures(
    tmp_path: Path,
    valid_from_delta: timedelta,
    valid_until_delta: timedelta,
    expected: str,
) -> None:
    observed_at = datetime.now(UTC).replace(microsecond=0)
    startup = tmp_path / "startup-kit"
    startup.mkdir(mode=0o700)
    certificate = startup / "client.crt"
    write_certificate(
        certificate,
        valid_from=observed_at + valid_from_delta,
        valid_until=observed_at + valid_until_delta,
    )
    result = _certificate_check(
        certificate,
        startup_kit=startup,
        minimum_valid_days=14,
        restrict_to_startup_kit=True,
        now=observed_at,
    )
    assert result.ok is False
    assert result.status == expected


def test_certificate_symlink_and_out_of_root_are_rejected(tmp_path: Path) -> None:
    observed_at = datetime.now(UTC).replace(microsecond=0)
    startup = tmp_path / "startup-kit"
    startup.mkdir(mode=0o700)
    outside = tmp_path / "outside.crt"
    write_certificate(
        outside,
        valid_from=observed_at - timedelta(days=1),
        valid_until=observed_at + timedelta(days=60),
    )
    link = startup / "client.crt"
    link.symlink_to(outside)
    linked = _certificate_check(
        link,
        startup_kit=startup,
        minimum_valid_days=14,
        restrict_to_startup_kit=True,
        now=observed_at,
    )
    outside_result = _certificate_check(
        outside,
        startup_kit=startup,
        minimum_valid_days=14,
        restrict_to_startup_kit=True,
        now=observed_at,
    )
    assert linked.status == "symlink_rejected"
    assert outside_result.status == "insecure_path_permissions"


def test_gpu_probe_requires_an_eligible_device(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rarelink.site_agent.health.shutil.which", lambda _: "/bin/nvidia-smi")

    def run_low(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args[0],
            0,
            "NVIDIA GB10, 590.00, 12288, 512, 55\n",
            "",
        )

    monkeypatch.setattr("rarelink.site_agent.health.subprocess.run", run_low)
    low = _gpu_check(1024)
    assert low.ok is False
    assert low.status == "insufficient_free_memory"

    def run_ready(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args[0],
            0,
            "NVIDIA GB10, 590.00, 12288, 8192, 55\n",
            "",
        )

    monkeypatch.setattr("rarelink.site_agent.health.subprocess.run", run_ready)
    ready = _gpu_check(1024)
    assert ready.ok is True
    assert ready.details["eligible_device_count"] == 1


@pytest.mark.parametrize("failed_check", ["gpu", "memory", "disk", "certificate"])
def test_start_and_recover_are_blocked_until_preflight_passes(
    tmp_path: Path,
    failed_check: str,
) -> None:
    executor = RestartAwareExecutor()
    is_ready = False

    def health() -> HealthSnapshot:
        return snapshot(ready=is_ready, failed_check=None if is_ready else failed_check)

    client = TestClient(
        create_site_agent_app(settings(tmp_path), executor=executor, health_provider=health)
    )
    request = {
        "task_id": f"job-{failed_check}",
        "round_id": 1,
        "total_rounds": 3,
        "contract_sha256": CONTRACT,
    }
    blocked = client.post("/v1/tasks/start", json=request, headers=auth())
    assert blocked.status_code == 503
    assert executor.calls == []
    assert client.get("/v1/tasks", headers=auth()).json()[0]["state"] == "FAILED"

    is_ready = True
    recovered = client.post("/v1/tasks/recover", json=request, headers=auth())
    replay = client.post("/v1/tasks/recover", json=request, headers=auth())
    assert recovered.status_code == 200
    assert recovered.json()["record"]["state"] == "RUNNING"
    assert replay.json()["idempotent_replay"] is True
    assert executor.calls == ["recover"]


def test_restart_reconciles_executor_state_without_duplicate_start(tmp_path: Path) -> None:
    local_settings = settings(tmp_path)
    first_executor = RestartAwareExecutor(running_after_restart=True)
    first = TestClient(
        create_site_agent_app(
            local_settings,
            executor=first_executor,
            health_provider=lambda: snapshot(ready=True),
        )
    )
    request = {
        "task_id": "job-restart",
        "round_id": 2,
        "total_rounds": 5,
        "contract_sha256": CONTRACT,
    }
    assert first.post("/v1/tasks/start", json=request, headers=auth()).status_code == 200
    assert first_executor.calls == ["start"]

    stopped_executor = RestartAwareExecutor(running_after_restart=False)
    restarted = TestClient(
        create_site_agent_app(
            local_settings,
            executor=stopped_executor,
            health_provider=lambda: snapshot(ready=True),
        )
    )
    record = restarted.get("/v1/tasks", headers=auth()).json()[0]
    assert record["state"] == "FAILED"
    assert record["error_code"] == "ExecutorNotRunningAfterRestart"
    assert stopped_executor.calls == []

    recovered = restarted.post("/v1/tasks/recover", json=request, headers=auth())
    assert recovered.json()["record"]["state"] == "RUNNING"
    assert stopped_executor.calls == ["recover"]


def envelope(heartbeat_id: str = "heartbeat-reliability-001") -> dict[str, Any]:
    payload = {
        "heartbeat_id": heartbeat_id,
        "agent_version": "0.2.0",
        "status": "READY",
        "certificate_status": "VALID",
        "data_ready": True,
        "gpu_ready": True,
        "monai_ready": True,
        "nvflare_ready": True,
        "current_job_id": None,
        "current_round": 0,
        "total_rounds": 0,
        "free_memory_percent": 70.0,
        "free_disk_percent": 60.0,
        "receipt_sha256": "d" * 64,
        "captured_at": datetime.now(UTC).isoformat(),
        "contains_patient_data": False,
    }
    return {
        "schema_version": "rarelink-site-heartbeat-v1",
        "site_id": "hospital-a",
        "timestamp": 1000,
        "heartbeat_id": heartbeat_id,
        "payload": payload,
        "payload_sha256": "e" * 64,
        "algorithm": "HMAC-SHA256",
        "key_id": "key-id-001",
        "signature": "f" * 64,
    }


def test_heartbeat_outbox_persists_dedup_and_exponential_backoff(tmp_path: Path) -> None:
    path = tmp_path / "outbox" / "heartbeat.sqlite3"
    outbox = HeartbeatOutbox(path, BackoffPolicy(base_seconds=5, maximum_seconds=20))
    assert outbox.enqueue(envelope()) is not None
    assert outbox.record_failure(100) == 5
    assert outbox.state().next_attempt_at == 105

    restarted = HeartbeatOutbox(path, BackoffPolicy(base_seconds=5, maximum_seconds=20))
    assert restarted.state().pending_envelope["heartbeat_id"] == "heartbeat-reliability-001"
    assert restarted.record_failure(105) == 10
    restarted.record_accepted("heartbeat-reliability-001")
    assert restarted.state().pending_envelope is None
    assert restarted.state().consecutive_failures == 0
    assert restarted.enqueue(envelope()) is None
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_outbox_rejects_unreviewed_or_patient_payload_fields(tmp_path: Path) -> None:
    unsafe = envelope()
    unsafe["payload"]["patient_name"] = "must-never-persist"
    outbox = HeartbeatOutbox(tmp_path / "heartbeat.sqlite3")
    with pytest.raises(ValueError, match="reviewed schema"):
        outbox.enqueue(unsafe)
    assert "must-never-persist" not in str(outbox.state())


def test_state_databases_reject_symbolic_links(tmp_path: Path) -> None:
    target = tmp_path / "untrusted-target.sqlite3"
    target.write_text("not-a-database", encoding="utf-8")
    task_link = tmp_path / "task-state.sqlite3"
    outbox_link = tmp_path / "outbox.sqlite3"
    task_link.symlink_to(target)
    outbox_link.symlink_to(target)
    with pytest.raises(ValueError, match="symbolic link"):
        TaskStore(task_link)
    with pytest.raises(ValueError, match="symbolic link"):
        HeartbeatOutbox(outbox_link)


def test_reliable_forwarder_reuses_pending_id_after_disconnect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outbox = HeartbeatOutbox(
        tmp_path / "heartbeat.sqlite3",
        BackoffPolicy(base_seconds=5, maximum_seconds=20),
    )
    fetched: list[str] = []
    sent: list[str] = []

    def fetch(*args: Any, **kwargs: Any) -> dict[str, Any]:
        fetched.append("fetch")
        return envelope()

    def fail_send(**kwargs: Any) -> dict[str, Any]:
        sent.append(kwargs["envelope"]["heartbeat_id"])
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(push_site_heartbeat, "fetch_envelope", fetch)
    monkeypatch.setattr(push_site_heartbeat, "send_envelope", fail_send)
    first = push_site_heartbeat.reliable_forward_once(
        outbox=outbox,
        agent_url="http://127.0.0.1:9100",
        coordinator_url="https://coordinator.example",
        api_token="not-exported",
        demo_token="",
        timeout=1,
        now=100,
    )
    deferred = push_site_heartbeat.reliable_forward_once(
        outbox=outbox,
        agent_url="http://127.0.0.1:9100",
        coordinator_url="https://coordinator.example",
        api_token="not-exported",
        demo_token="",
        timeout=1,
        now=101,
    )
    assert first["retry_after_seconds"] == 5
    assert deferred["deferred"] is True
    assert fetched == ["fetch"]
    assert sent == ["heartbeat-reliability-001"]

    def succeed_send(**kwargs: Any) -> dict[str, Any]:
        sent.append(kwargs["envelope"]["heartbeat_id"])
        return {"site_id": "hospital-a", "status": "READY"}

    monkeypatch.setattr(push_site_heartbeat, "send_envelope", succeed_send)
    completed = push_site_heartbeat.reliable_forward_once(
        outbox=outbox,
        agent_url="http://127.0.0.1:9100",
        coordinator_url="https://coordinator.example",
        api_token="not-exported",
        demo_token="",
        timeout=1,
        now=105,
    )
    assert completed["forwarded"] is True
    assert fetched == ["fetch"]
    assert sent == ["heartbeat-reliability-001", "heartbeat-reliability-001"]
    assert outbox.state().pending_envelope is None


def test_reliable_forwarder_replaces_expired_pending_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outbox = HeartbeatOutbox(
        tmp_path / "heartbeat.sqlite3",
        BackoffPolicy(
            base_seconds=5,
            maximum_seconds=20,
            maximum_envelope_age_seconds=30,
        ),
    )
    stale = envelope("heartbeat-stale-001")
    stale["timestamp"] = 100
    assert outbox.enqueue(stale) is not None
    replacement = envelope("heartbeat-fresh-002")
    replacement["timestamp"] = 200
    sent: list[str] = []

    monkeypatch.setattr(
        push_site_heartbeat,
        "fetch_envelope",
        lambda *args, **kwargs: replacement,
    )

    def send(**kwargs: Any) -> dict[str, Any]:
        sent.append(kwargs["envelope"]["heartbeat_id"])
        return {"site_id": "hospital-a", "status": "READY"}

    monkeypatch.setattr(push_site_heartbeat, "send_envelope", send)
    result = push_site_heartbeat.reliable_forward_once(
        outbox=outbox,
        agent_url="http://127.0.0.1:9100",
        coordinator_url="https://coordinator.example",
        api_token="not-exported",
        demo_token="",
        timeout=1,
        now=200,
    )
    assert result["forwarded"] is True
    assert sent == ["heartbeat-fresh-002"]
    assert outbox.state().last_accepted_heartbeat_id == "heartbeat-fresh-002"
