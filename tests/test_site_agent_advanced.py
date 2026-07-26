from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
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
from rarelink.site_agent.health import (
    _certificate_check,
    _cpu_check,
    _dependency_check,
    _gpu_check,
)
from rarelink.site_agent.schemas import CheckResult, HealthSnapshot, TaskRecord, utc_now

TOKEN = "site-agent-advanced-token-00000000"
HMAC_KEY = "site-agent-advanced-hmac-key-00000000000"
CONTRACT = "9" * 64


class PauseExecutor:
    def __init__(self, *, pause_fails: bool = False) -> None:
        self.pause_fails = pause_fails
        self.calls: list[str] = []

    def start(self, task: TaskRecord) -> str:
        self.calls.append("start")
        return "nvflare-job-advanced"

    def stop(self, task: TaskRecord) -> str:
        self.calls.append("stop")
        return "nvflare-job-advanced"

    def pause(self, task: TaskRecord) -> str:
        self.calls.append("pause")
        if self.pause_fails:
            raise RuntimeError("sensitive executor diagnostic must not escape")
        return "nvflare-job-advanced"

    def resume(self, task: TaskRecord) -> str:
        self.calls.append("resume")
        return "nvflare-job-advanced"

    def recover(self, task: TaskRecord) -> str:
        self.calls.append("recover")
        return "nvflare-job-advanced"

    def is_running(self, task: TaskRecord) -> bool:
        return True


def healthy() -> HealthSnapshot:
    return HealthSnapshot(
        ready=True,
        checked_at=utc_now(),
        checks={
            name: CheckResult(ok=True, status="ready")
            for name in (
                "gpu",
                "disk",
                "memory",
                "cpu",
                "dependencies",
                "certificate",
                "dataset_manifest",
                "startup_kit",
            )
        },
    )


def settings(tmp_path: Path, **updates: Any) -> SiteAgentSettings:
    site_root = tmp_path / "site"
    startup = site_root / "startup-kit"
    (startup / "startup").mkdir(parents=True)
    manifest = site_root / "manifest.json"
    manifest.write_text('{"cases":[]}', encoding="utf-8")
    values: dict[str, Any] = {
        "_env_file": None,
        "site_id": "hospital-a",
        "dataset_manifest": manifest,
        "artifact_root": tmp_path / "artifacts",
        "startup_kit": startup,
        "state_database": tmp_path / "state.sqlite3",
        "api_token": TOKEN,
        "receipt_hmac_key": HMAC_KEY,
        "required_modules": "",
    }
    values.update(updates)
    return SiteAgentSettings(**values)


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def request(task_id: str = "job-advanced") -> dict[str, Any]:
    return {
        "task_id": task_id,
        "round_id": 2,
        "total_rounds": 5,
        "contract_sha256": CONTRACT,
    }


def test_gpu_receipt_has_allowlisted_device_driver_cuda_and_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rarelink.site_agent.health.shutil.which", lambda _: "/bin/nvidia-smi")

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command == ["/bin/nvidia-smi"]:
            return subprocess.CompletedProcess(
                command,
                0,
                "NVIDIA-SMI 590.00 Driver Version: 590.00 CUDA Version: 13.0",
                "",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            "NVIDIA GB10, 590.00, 131072, 120000, 62\n",
            "",
        )

    monkeypatch.setattr("rarelink.site_agent.health.subprocess.run", runner)
    result = _gpu_check(1024, 85)
    assert result.ok is True
    assert result.details["cuda_version"] == "13.0"
    assert result.details["devices"] == [
        {
            "name": "NVIDIA GB10",
            "driver_version": "590.00",
            "total_memory_mib": 131072,
            "free_memory_mib": 120000,
            "temperature_c": 62,
        }
    ]
    assert result.details["device_uuid_exported"] is False
    assert result.details["device_serial_exported"] is False

    def overheated(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command == ["/bin/nvidia-smi"]:
            return runner(command, **kwargs)
        return subprocess.CompletedProcess(
            command,
            0,
            "NVIDIA GB10, 590.00, 131072, 120000, 91\n",
            "",
        )

    monkeypatch.setattr("rarelink.site_agent.health.subprocess.run", overheated)
    hot = _gpu_check(1024, 85)
    assert hot.ok is False
    assert hot.status == "temperature_exceeded"


def test_cpu_load_and_dependency_contract_are_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rarelink.site_agent.health.os.cpu_count", lambda: 4)
    monkeypatch.setattr("rarelink.site_agent.health.os.getloadavg", lambda: (3.8, 2.0, 1.0))
    busy = _cpu_check(90)
    assert busy.ok is False
    assert busy.status == "load_exceeded"
    assert busy.details["normalized_load_percent"] == 95

    monkeypatch.setattr(
        "rarelink.site_agent.health.importlib.util.find_spec",
        lambda _: object(),
    )
    versions = {"torch": "2.9.0", "monai": "1.6.0", "nvflare": "2.7.2"}
    monkeypatch.setattr(
        "rarelink.site_agent.health.importlib.metadata.version",
        lambda name: versions[name],
    )
    first = _dependency_check(("torch", "monai", "nvflare"))
    second = _dependency_check(("nvflare", "torch", "monai"))
    assert first.ok is True
    assert first.details["versions"] == versions
    assert first.details["dependency_contract_sha256"] == second.details[
        "dependency_contract_sha256"
    ]


def build_pki(
    tmp_path: Path,
    *,
    identity: str = "hospital-a",
    san_identity: str | None = None,
    revoked: bool = False,
) -> tuple[Path, Path, Path, datetime]:
    observed_at = datetime.now(UTC).replace(microsecond=0)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "RareLink Test CA")])
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(observed_at - timedelta(days=2))
        .not_valid_after(observed_at + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, identity)])
    leaf_certificate = (
        x509.CertificateBuilder()
        .subject_name(leaf_name)
        .issuer_name(ca_name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(observed_at - timedelta(days=1))
        .not_valid_after(observed_at + timedelta(days=60))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(san_identity or identity)]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    crl_builder = (
        x509.CertificateRevocationListBuilder()
        .issuer_name(ca_name)
        .last_update(observed_at - timedelta(hours=1))
        .next_update(observed_at + timedelta(days=7))
    )
    if revoked:
        crl_builder = crl_builder.add_revoked_certificate(
            x509.RevokedCertificateBuilder()
            .serial_number(leaf_certificate.serial_number)
            .revocation_date(observed_at - timedelta(minutes=30))
            .build()
        )
    crl = crl_builder.sign(ca_key, hashes.SHA256())

    startup = tmp_path / "startup"
    pki_root = tmp_path / "public-pki"
    startup.mkdir(mode=0o700, parents=True)
    pki_root.mkdir(mode=0o700, parents=True)
    leaf_path = startup / "client.crt"
    ca_path = pki_root / "ca-bundle.pem"
    crl_path = pki_root / "site.crl"
    leaf_path.write_bytes(leaf_certificate.public_bytes(serialization.Encoding.PEM))
    ca_path.write_bytes(ca_certificate.public_bytes(serialization.Encoding.PEM))
    crl_path.write_bytes(crl.public_bytes(serialization.Encoding.PEM))
    for path in (leaf_path, ca_path, crl_path):
        path.chmod(0o600)
    return leaf_path, ca_path, crl_path, observed_at


def test_offline_chain_identity_and_crl_validation(tmp_path: Path) -> None:
    leaf, ca_bundle, crl, observed_at = build_pki(tmp_path)
    verified = _certificate_check(
        leaf,
        startup_kit=leaf.parent,
        minimum_valid_days=14,
        restrict_to_startup_kit=True,
        expected_identity="hospital-a",
        ca_bundle=ca_bundle,
        require_chain=True,
        crl_file=crl,
        require_crl=True,
        now=observed_at,
    )
    assert verified.ok is True
    assert verified.details["chain_status"] == "verified"
    assert verified.details["crl_status"] == "not_revoked"
    assert verified.details["ocsp_checked"] is False
    assert verified.details["private_key_content_read"] is False

    wrong_identity = _certificate_check(
        leaf,
        startup_kit=leaf.parent,
        minimum_valid_days=14,
        restrict_to_startup_kit=True,
        expected_identity="hospital-b",
        ca_bundle=ca_bundle,
        require_chain=True,
        crl_file=crl,
        require_crl=True,
        now=observed_at,
    )
    assert wrong_identity.status == "identity_mismatch"

    san_leaf, san_ca, san_crl, san_observed_at = build_pki(
        tmp_path / "san-authoritative",
        identity="hospital-a",
        san_identity="hospital-b",
    )
    san_mismatch = _certificate_check(
        san_leaf,
        startup_kit=san_leaf.parent,
        minimum_valid_days=14,
        restrict_to_startup_kit=True,
        expected_identity="hospital-a",
        ca_bundle=san_ca,
        require_chain=True,
        crl_file=san_crl,
        require_crl=True,
        now=san_observed_at,
    )
    assert san_mismatch.status == "identity_mismatch"


def test_revoked_or_missing_crl_fails_closed(tmp_path: Path) -> None:
    leaf, ca_bundle, crl, observed_at = build_pki(tmp_path, revoked=True)
    revoked = _certificate_check(
        leaf,
        startup_kit=leaf.parent,
        minimum_valid_days=14,
        restrict_to_startup_kit=True,
        expected_identity="hospital-a",
        ca_bundle=ca_bundle,
        require_chain=True,
        crl_file=crl,
        require_crl=True,
        now=observed_at,
    )
    missing = _certificate_check(
        leaf,
        startup_kit=leaf.parent,
        minimum_valid_days=14,
        restrict_to_startup_kit=True,
        expected_identity="hospital-a",
        ca_bundle=ca_bundle,
        require_chain=True,
        crl_file=None,
        require_crl=True,
        now=observed_at,
    )
    assert revoked.status == "certificate_revoked"
    assert missing.status == "crl_missing"


def test_untrusted_ca_bundle_fails_chain_validation(tmp_path: Path) -> None:
    leaf, _trusted_ca, _crl, observed_at = build_pki(tmp_path / "site-a")
    _other_leaf, untrusted_ca, _other_crl, _ = build_pki(tmp_path / "site-b")
    result = _certificate_check(
        leaf,
        startup_kit=leaf.parent,
        minimum_valid_days=14,
        restrict_to_startup_kit=True,
        expected_identity="hospital-a",
        ca_bundle=untrusted_ca,
        require_chain=True,
        crl_file=None,
        require_crl=False,
        now=observed_at,
    )
    assert result.ok is False
    assert result.status == "invalid"


def write_checkpoint_receipt(
    root: Path,
    receipt_path: Path,
    *,
    task_id: str = "job-checkpoint",
    contract_sha256: str = CONTRACT,
    content: bytes = b"verified-model-checkpoint",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    checkpoint = root / "round-2.ckpt"
    checkpoint.write_bytes(content)
    checkpoint.chmod(0o600)
    digest = hashlib.sha256(content).hexdigest()
    receipt_path.write_text(
        json.dumps(
            {
                "schema_version": "rarelink-checkpoint-receipt-v1",
                "checkpoint_id": "checkpoint-round-2",
                "task_id": task_id,
                "round_id": 2,
                "contract_sha256": contract_sha256,
                "checkpoint_file": "round-2.ckpt",
                "checkpoint_sha256": digest,
                "size_bytes": len(content),
                "created_at": datetime.now(UTC).isoformat(),
                "contains_patient_data": False,
                "path_exported": False,
            }
        ),
        encoding="utf-8",
    )
    receipt_path.chmod(0o600)


def test_pause_is_idempotent_and_recover_requires_untampered_checkpoint(
    tmp_path: Path,
) -> None:
    checkpoint_root = tmp_path / "checkpoints"
    checkpoint_receipt = tmp_path / "checkpoint-receipt.json"
    local_settings = settings(
        tmp_path,
        checkpoint_root=checkpoint_root,
        checkpoint_receipt=checkpoint_receipt,
        require_checkpoint_for_pause=True,
        require_checkpoint_for_recover=True,
    )
    executor = PauseExecutor()
    client = TestClient(
        create_site_agent_app(local_settings, executor=executor, health_provider=healthy)
    )
    task_request = request("job-checkpoint")
    started = client.post("/v1/tasks/start", json=task_request, headers=auth())
    assert started.status_code == 200
    assert started.json()["record"]["training_stage"] == "training"
    assert started.json()["record"]["active_since"] is not None
    assert started.json()["record"]["resource_status"]["gpu"] == "ready"
    write_checkpoint_receipt(checkpoint_root, checkpoint_receipt)

    paused = client.post("/v1/tasks/pause", json=task_request, headers=auth())
    replay = client.post("/v1/tasks/pause", json=task_request, headers=auth())
    assert paused.status_code == 200
    assert paused.json()["record"]["training_stage"] == "paused"
    assert paused.json()["record"]["active_since"] is None
    assert paused.json()["record"]["active_runtime_seconds"] > 0
    assert paused.json()["record"]["checkpoint"]["path_exported"] is False
    assert paused.json()["record"]["receipt"]["checkpoint_sha256"] == paused.json()[
        "record"
    ]["checkpoint"]["checkpoint_sha256"]
    assert replay.json()["idempotent_replay"] is True
    assert executor.calls == ["start", "pause"]

    (checkpoint_root / "round-2.ckpt").write_bytes(b"tampered")
    blocked = client.post("/v1/tasks/recover", json=task_request, headers=auth())
    assert blocked.status_code == 412
    assert executor.calls == ["start", "pause"]

    write_checkpoint_receipt(
        checkpoint_root,
        checkpoint_receipt,
        content=b"different-but-self-consistent-checkpoint",
    )
    replaced = client.post("/v1/tasks/recover", json=task_request, headers=auth())
    assert replaced.status_code == 412
    assert executor.calls == ["start", "pause"]

    write_checkpoint_receipt(checkpoint_root, checkpoint_receipt)
    recovered = client.post("/v1/tasks/recover", json=task_request, headers=auth())
    recovered_replay = client.post("/v1/tasks/recover", json=task_request, headers=auth())
    assert recovered.status_code == 200
    assert recovered.json()["record"]["training_stage"] == "training"
    assert recovered_replay.json()["idempotent_replay"] is True
    assert executor.calls == ["start", "pause", "resume"]


def test_pause_rejects_missing_checkpoint_before_signalling_executor(tmp_path: Path) -> None:
    local_settings = settings(
        tmp_path,
        checkpoint_root=tmp_path / "checkpoints",
        checkpoint_receipt=tmp_path / "missing-receipt.json",
        require_checkpoint_for_pause=True,
    )
    executor = PauseExecutor()
    client = TestClient(
        create_site_agent_app(local_settings, executor=executor, health_provider=healthy)
    )
    task_request = request("job-no-checkpoint")
    assert client.post("/v1/tasks/start", json=task_request, headers=auth()).status_code == 200
    blocked = client.post("/v1/tasks/pause", json=task_request, headers=auth())
    assert blocked.status_code == 412
    assert executor.calls == ["start"]
    assert client.get("/v1/tasks", headers=auth()).json()[0]["state"] == "RUNNING"


def test_pause_executor_failure_is_safe_and_does_not_echo_diagnostic(tmp_path: Path) -> None:
    executor = PauseExecutor(pause_fails=True)
    client = TestClient(
        create_site_agent_app(settings(tmp_path), executor=executor, health_provider=healthy)
    )
    task_request = request("job-pause-failure")
    assert client.post("/v1/tasks/start", json=task_request, headers=auth()).status_code == 200
    response = client.post("/v1/tasks/pause", json=task_request, headers=auth())
    assert response.status_code == 503
    assert "sensitive executor diagnostic" not in response.text
    assert client.get("/v1/tasks", headers=auth()).json()[0]["state"] == "FAILED"


def test_restart_fails_closed_when_persisted_task_receipt_is_modified(
    tmp_path: Path,
) -> None:
    local_settings = settings(tmp_path)
    executor = PauseExecutor()
    client = TestClient(
        create_site_agent_app(local_settings, executor=executor, health_provider=healthy)
    )
    task_request = request("job-receipt-tamper")
    assert client.post("/v1/tasks/start", json=task_request, headers=auth()).status_code == 200

    with sqlite3.connect(local_settings.state_database) as connection:
        encoded = connection.execute(
            "SELECT record_json FROM site_tasks WHERE task_id = ? AND round_id = ?",
            ("job-receipt-tamper", 2),
        ).fetchone()[0]
        payload = json.loads(encoded)
        payload["receipt"]["signature"] = "0" * 64
        connection.execute(
            "UPDATE site_tasks SET record_json = ? WHERE task_id = ? AND round_id = ?",
            (json.dumps(payload), "job-receipt-tamper", 2),
        )

    restarted = TestClient(
        create_site_agent_app(local_settings, executor=executor, health_provider=healthy)
    )
    record = restarted.get("/v1/tasks", headers=auth()).json()[0]
    assert record["state"] == "FAILED"
    assert record["error_code"] == "InvalidStoredReceipt"
    assert executor.calls == ["start"]
