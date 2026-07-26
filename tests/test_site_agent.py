from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from rarelink.security.site_auth import verify_heartbeat_signature
from rarelink.site_agent import SiteAgentSettings, create_site_agent_app
from rarelink.site_agent.heartbeat import to_central_heartbeat
from rarelink.site_agent.receipt import ReceiptSigner
from rarelink.site_agent.schemas import CheckResult, HealthSnapshot, TaskRecord, utc_now

TOKEN = "site-agent-test-token-000000"
HMAC_KEY = "site-agent-test-hmac-key-000000000000"
CONTRACT = "a" * 64


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def start(self, task: TaskRecord) -> str:
        self.calls.append(("start", task.task_id, task.round_id))
        return "nvflare-job-test-001"

    def stop(self, task: TaskRecord) -> str:
        self.calls.append(("stop", task.task_id, task.round_id))
        return task.executor_ref or "nvflare-job-test-001"

    def recover(self, task: TaskRecord) -> str:
        self.calls.append(("recover", task.task_id, task.round_id))
        return task.executor_ref or "nvflare-job-test-001"


def settings(tmp_path: Path) -> SiteAgentSettings:
    manifest = tmp_path / "private" / "manifest.json"
    manifest.parent.mkdir()
    manifest.write_text('{"cases":[]}', encoding="utf-8")
    startup = tmp_path / "private" / "startup-kit"
    (startup / "startup").mkdir(parents=True)
    return SiteAgentSettings(
        _env_file=None,
        site_id="hospital-a",
        dataset_manifest=manifest,
        artifact_root=tmp_path / "artifacts",
        startup_kit=startup,
        state_database=tmp_path / "state.sqlite3",
        api_token=TOKEN,
        receipt_hmac_key=HMAC_KEY,
        required_modules="",
    )


def healthy() -> HealthSnapshot:
    return HealthSnapshot(
        ready=True,
        checked_at=utc_now(),
        checks={
            "gpu": CheckResult(ok=True, status="available", details={"device_count": 1}),
            "memory": CheckResult(ok=True, status="sufficient", details={"free_percent": 80}),
            "cpu": CheckResult(ok=True, status="sufficient"),
            "disk": CheckResult(ok=True, status="sufficient", details={"free_percent": 70}),
            "certificate": CheckResult(ok=True, status="valid"),
            "dataset_manifest": CheckResult(
                ok=True,
                status="receipt_verified",
                details={"dataset_fingerprint": "d" * 64},
            ),
            "dependencies": CheckResult(
                ok=True,
                status="available",
                details={"versions": {"monai": "1.5", "nvflare": "2.7"}},
            ),
            "startup_kit": CheckResult(ok=True, status="present"),
        },
    )


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_site_agent_requires_auth_and_heartbeat_is_deidentified(tmp_path: Path) -> None:
    local_settings = settings(tmp_path)
    app = create_site_agent_app(local_settings, health_provider=healthy)
    client = TestClient(app)

    assert client.get("/health/live").status_code == 200
    assert client.get("/v1/site/heartbeat").status_code == 401

    response = client.get("/v1/site/heartbeat", headers=auth())
    assert response.status_code == 200
    body = response.json()
    serialized = response.text
    assert body["site_id"] == "hospital-a"
    assert body["payload"]["contains_patient_data"] is False
    assert str(local_settings.dataset_manifest) not in serialized
    assert TOKEN not in serialized
    assert HMAC_KEY not in serialized
    assert len(body["signature"]) == 64
    verify_heartbeat_signature(
        site_id="hospital-a",
        timestamp=body["timestamp"],
        heartbeat_id=body["heartbeat_id"],
        payload=body["payload"],
        secret=HMAC_KEY,
        signature=body["signature"],
        max_age_seconds=60,
        now=body["timestamp"],
    )


def test_start_is_idempotent_and_contract_mismatch_is_rejected(tmp_path: Path) -> None:
    executor = RecordingExecutor()
    app = create_site_agent_app(settings(tmp_path), executor=executor, health_provider=healthy)
    client = TestClient(app)
    request = {"task_id": "job-001", "round_id": 1, "contract_sha256": CONTRACT}

    first = client.post("/v1/tasks/start", json=request, headers=auth())
    replay = client.post("/v1/tasks/start", json=request, headers=auth())
    mismatch = client.post(
        "/v1/tasks/start",
        json={**request, "contract_sha256": "b" * 64},
        headers=auth(),
    )

    assert first.status_code == 200
    assert first.json()["record"]["state"] == "RUNNING"
    assert replay.json()["idempotent_replay"] is True
    assert executor.calls == [("start", "job-001", 1)]
    assert mismatch.status_code == 409


def test_stop_and_recover_follow_safe_state_machine(tmp_path: Path) -> None:
    executor = RecordingExecutor()
    local_settings = settings(tmp_path)
    app = create_site_agent_app(local_settings, executor=executor, health_provider=healthy)
    client = TestClient(app)
    request = {"task_id": "job-002", "round_id": 3, "contract_sha256": CONTRACT}

    assert client.post("/v1/tasks/start", json=request, headers=auth()).status_code == 200
    stopped = client.post("/v1/tasks/stop", json=request, headers=auth())
    stopped_replay = client.post("/v1/tasks/stop", json=request, headers=auth())
    recovered = client.post("/v1/tasks/recover", json=request, headers=auth())

    assert stopped.json()["record"]["state"] == "STOPPED"
    assert stopped_replay.json()["idempotent_replay"] is True
    assert recovered.json()["record"]["state"] == "RUNNING"
    assert executor.calls == [
        ("start", "job-002", 3),
        ("stop", "job-002", 3),
        ("recover", "job-002", 3),
    ]

    persisted = TestClient(
        create_site_agent_app(local_settings, executor=executor, health_provider=healthy)
    ).get("/v1/tasks", headers=auth())
    assert persisted.json()[0]["state"] == "RUNNING"


def test_receipt_detects_tampering_without_exposing_key(tmp_path: Path) -> None:
    executor = RecordingExecutor()
    local_settings = settings(tmp_path)
    app = create_site_agent_app(local_settings, executor=executor, health_provider=healthy)
    client = TestClient(app)
    request = {"task_id": "job-003", "round_id": 1, "contract_sha256": CONTRACT}

    receipt_payload = client.post("/v1/tasks/start", json=request, headers=auth()).json()[
        "record"
    ]["receipt"]
    signer = ReceiptSigner("hospital-a", HMAC_KEY)
    from rarelink.site_agent.schemas import SignedReceipt

    receipt = SignedReceipt.model_validate(receipt_payload)
    assert signer.verify_task(receipt) is True
    assert HMAC_KEY not in str(receipt_payload)

    tampered = receipt.model_copy(update={"revision": receipt.revision + 1})
    assert signer.verify_task(tampered) is False


def test_disabled_executor_fails_closed(tmp_path: Path) -> None:
    app = create_site_agent_app(settings(tmp_path), health_provider=healthy)
    client = TestClient(app)
    request = {"task_id": "job-004", "round_id": 1, "contract_sha256": CONTRACT}

    response = client.post("/v1/tasks/start", json=request, headers=auth())
    assert response.status_code == 503
    records = client.get("/v1/tasks", headers=auth()).json()
    assert records[0]["state"] == "FAILED"
    assert "site_task_executor_not_configured" not in response.text


def test_central_heartbeat_mapping_is_lossless_and_schema_compatible(tmp_path: Path) -> None:
    from rarelink.domain import PhysicalSiteHeartbeat

    executor = RecordingExecutor()
    local_settings = settings(tmp_path)
    app = create_site_agent_app(local_settings, executor=executor, health_provider=healthy)
    client = TestClient(app)
    request = {
        "task_id": "job-005",
        "round_id": 2,
        "total_rounds": 5,
        "contract_sha256": CONTRACT,
    }
    record_payload = client.post("/v1/tasks/start", json=request, headers=auth()).json()["record"]
    record = TaskRecord.model_validate(record_payload)

    payload = to_central_heartbeat(
        heartbeat_id="heartbeat-test-005",
        health=healthy(),
        tasks=[record],
    )
    validated = PhysicalSiteHeartbeat.model_validate(payload)

    assert validated.status == "TRAINING"
    assert validated.current_job_id == "job-005"
    assert validated.current_round == 2
    assert validated.total_rounds == 5
    assert validated.monai_ready is True
    assert validated.nvflare_ready is True
    assert validated.contains_patient_data is False
