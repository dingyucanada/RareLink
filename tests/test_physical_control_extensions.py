import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean, pstdev

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from rarelink.api.main import app
from rarelink.config import Settings, get_settings
from rarelink.database import get_session
from rarelink.models import PhysicalControlEvent, PhysicalFederationJob
from rarelink.services.physical_controller import (
    CommandResult,
    InMemoryPhysicalJobStore,
    JobValidationError,
    NvflareCliAdapter,
    PhysicalFederationController,
)
from rarelink.services.physical_events import encode_sse, fetch_safe_job_events
from rarelink.services.physical_results import (
    parse_aggregate_metrics,
    parse_client_registry,
)

EXPECTED_SITES = ("hospital-a", "hospital-b", "hospital-c")


def exported_job(tmp_path: Path) -> Path:
    root = tmp_path / "rarelink-fedavg-job"
    root.mkdir()
    (root / "meta.json").write_text(
        json.dumps({"name": "rarelink-physical-fedavg", "deploy_map": {}}),
        encoding="utf-8",
    )
    (root / "rarelink-job-receipt.json").write_text(
        json.dumps(
            {
                "schema_version": "rarelink-physical-job-export-v1",
                "strategy": "fedavg",
                "rounds": 5,
                "local_epochs": 1,
                "expected_sites": list(EXPECTED_SITES),
                "local_only_manifest_required": True,
                "dataset_receipt_required": True,
                "update_guard": {
                    "schema_version": "rarelink-update-guard-contract-v1",
                    "transfer_type": "DIFF",
                    "max_l2_norm": 50.0,
                    "minimum_cosine_similarity": -0.25,
                    "late_round_updates_rejected": True,
                    "duplicate_site_round_updates_rejected": True,
                    "durable_replay_registry_required": True,
                    "raw_update_receipts_exported": False,
                },
                "patient_data_packaged": False,
                "certificates_packaged": False,
                "private_keys_packaged": False,
            }
        ),
        encoding="utf-8",
    )
    return root


def metrics_summary() -> dict[str, object]:
    dice = [0.8, 0.7, 0.9]
    hd95 = [4.0, 5.0, 3.0]
    return {
        "mean_dice": fmean(dice),
        "worst_site_dice": min(dice),
        "site_dice_std": pstdev(dice),
        "hd95": fmean(hd95),
        "sites": [
            {
                "site_id": site_id,
                "dice": dice[index],
                "hd95": hd95[index],
                "sample_count": 8 + index,
            }
            for index, site_id in enumerate(EXPECTED_SITES)
        ],
    }


def test_client_registry_is_strict_and_never_relays_tokens() -> None:
    receipt = parse_client_registry(
        {
            "status": "ok",
            "data": {
                "clients": [
                    {"name": "hospital-a", "status": "CONNECTED", "token": "secret-a"},
                    {"name": "hospital-b", "status": "RUNNING", "token": "secret-b"},
                ]
            },
        },
        EXPECTED_SITES,
    )

    assert receipt["connected_sites"] == ["hospital-a", "hospital-b"]
    assert receipt["missing_sites"] == ["hospital-c"]
    assert "secret-a" not in json.dumps(receipt)
    assert receipt["clients"][2] == {
        "site_id": "hospital-c",
        "state": "NOT_REPORTED",
        "connected": False,
    }
    mapped = parse_client_registry(
        {
            "clients": {
                "hospital-a": {"status": "READY", "token": "must-not-export"},
            }
        },
        EXPECTED_SITES,
    )
    assert mapped["connected_sites"] == ["hospital-a"]
    assert "must-not-export" not in json.dumps(mapped)
    with pytest.raises(JobValidationError, match="unexpected site"):
        parse_client_registry(
            {"clients": [{"name": "attacker", "status": "CONNECTED"}]},
            EXPECTED_SITES,
        )


def test_client_registry_uses_nvflare_system_status_json_command(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def runner(command):  # type: ignore[no-untyped-def]
        commands.append(list(command))
        return CommandResult(0, '{"status":"ok","data":{"clients":[]}}')

    NvflareCliAdapter(runner=runner).client_registry(
        tmp_path / "admin-kit",
        EXPECTED_SITES,
    )

    assert commands == [
        [
            "nvflare",
            "system",
            "status",
            "client",
            *EXPECTED_SITES,
            "--startup-kit",
            str((tmp_path / "admin-kit").resolve()),
            "--format",
            "json",
        ]
    ]


def test_aggregate_metrics_recomputes_three_site_claims() -> None:
    receipt = parse_aggregate_metrics(metrics_summary(), EXPECTED_SITES)

    assert receipt["site_count"] == 3
    assert len(receipt["receipt_sha256"]) == 64
    tampered = metrics_summary()
    tampered["mean_dice"] = 0.99
    with pytest.raises(JobValidationError, match="does not match"):
        parse_aggregate_metrics(tampered, EXPECTED_SITES)
    leaking = metrics_summary()
    leaking["patient_id"] = "forbidden"
    with pytest.raises(JobValidationError, match="unsupported"):
        parse_aggregate_metrics(leaking, EXPECTED_SITES)


class DownloadRunner:
    def __init__(self, model_bytes: bytes, *, symlink_model: bool = False):
        self.model_bytes = model_bytes
        self.symlink_model = symlink_model
        self.commands: list[list[str]] = []

    def __call__(self, command):  # type: ignore[no-untyped-def]
        command = list(command)
        self.commands.append(command)
        if command[1:3] == ["job", "submit"]:
            return CommandResult(0, '{"job_id":"flare-result-001"}')
        if command[1:3] == ["job", "meta"]:
            return CommandResult(
                0,
                json.dumps(
                    {
                        "status": "COMPLETED",
                        "current_round": 5,
                        "received_from": list(EXPECTED_SITES),
                        "received_updates": 3,
                        "aggregate_metrics": metrics_summary(),
                    }
                ),
            )
        if command[1:3] == ["job", "download"]:
            output_root = Path(command[command.index("-o") + 1])
            download_root = output_root / "flare-result-001"
            workspace = download_root / "workspace"
            metrics_dir = workspace / "metrics"
            metrics_dir.mkdir(parents=True)
            model = workspace / "FL_global_model.pt"
            metrics = metrics_dir / "metrics_summary.json"
            model.write_bytes(self.model_bytes)
            exported_model = model
            if self.symlink_model:
                exported_model = workspace / "linked-global-model.pt"
                exported_model.symlink_to(model.name)
            metrics.write_text(json.dumps(metrics_summary()), encoding="utf-8")
            return CommandResult(
                0,
                json.dumps(
                    {
                        "status": "ok",
                        "data": {
                            "job_id": "flare-result-001",
                            "download_path": str(download_root),
                            "artifacts": {
                                "global_model": str(exported_model),
                                "metrics_summary": str(metrics),
                            },
                        },
                    }
                ),
            )
        raise AssertionError(command)


def test_controlled_result_archive_and_ready_for_review(tmp_path: Path) -> None:
    model_bytes = b"verified-global-model"
    runner = DownloadRunner(model_bytes)
    controller = PhysicalFederationController(
        NvflareCliAdapter(runner=runner),
        InMemoryPhysicalJobStore(),
    )
    controller.register("physical-result-001", exported_job(tmp_path))
    controller.submit(
        "physical-result-001",
        admin_kit=tmp_path / "admin-kit",
        submit_token="archive-token-001",
    )
    controller.status("physical-result-001", admin_kit=tmp_path / "admin-kit")
    before = controller.review_readiness("physical-result-001")
    assert before["review_status"] == "BLOCKED"

    receipt = controller.download_and_archive_results(
        "physical-result-001",
        admin_kit=tmp_path / "admin-kit",
        artifact_root=tmp_path / "managed",
        expected_sha256=hashlib.sha256(model_bytes).hexdigest(),
    )

    assert receipt["archived"] is True
    assert receipt["source_path_exported"] is False
    assert str(tmp_path) not in json.dumps(receipt)
    ready = controller.review_readiness("physical-result-001")
    assert ready["review_status"] == "READY_FOR_REVIEW"
    assert ready["ready"] is True
    assert runner.commands[-1][1:4] == ["job", "download", "flare-result-001"]
    assert "--format" in runner.commands[-1]
    assert "-o" in runner.commands[-1]


def test_controlled_result_archive_rejects_symlink_artifact(tmp_path: Path) -> None:
    model_bytes = b"verified-global-model"
    runner = DownloadRunner(model_bytes, symlink_model=True)
    controller = PhysicalFederationController(
        NvflareCliAdapter(runner=runner),
        InMemoryPhysicalJobStore(),
    )
    controller.register("physical-result-link", exported_job(tmp_path))
    controller.submit(
        "physical-result-link",
        admin_kit=tmp_path / "admin-kit",
        submit_token="archive-token-link",
    )
    controller.status("physical-result-link", admin_kit=tmp_path / "admin-kit")

    with pytest.raises(JobValidationError, match="symbolic links"):
        controller.download_and_archive_results(
            "physical-result-link",
            admin_kit=tmp_path / "admin-kit",
            artifact_root=tmp_path / "managed",
            expected_sha256=hashlib.sha256(model_bytes).hexdigest(),
        )


def test_sse_cursor_reconnects_and_exports_only_safe_fields() -> None:
    database = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(database)
    with Session(database) as session:
        session.add_all(
            [
                PhysicalControlEvent(
                    event_id="physical-event-aaaaaaaaaaaa",
                    action="job.submitted",
                    actor="private-operator",
                    resource_type="physical-job",
                    resource_id="physical-001",
                    outcome="accepted",
                    payload_json='{"private_key":"never-export"}',
                    previous_hash="0" * 64,
                    event_hash="1" * 64,
                    algorithm="HMAC-SHA256",
                    created_at=datetime.now(UTC),
                ),
                PhysicalControlEvent(
                    event_id="physical-event-bbbbbbbbbbbb",
                    action="job.status-synchronized",
                    actor="private-operator",
                    resource_type="physical-job",
                    resource_id="physical-001",
                    outcome="accepted",
                    payload_json='{"model_path":"/secret/path"}',
                    previous_hash="1" * 64,
                    event_hash="2" * 64,
                    algorithm="HMAC-SHA256",
                    created_at=datetime.now(UTC),
                ),
            ]
        )
        session.commit()
        events = fetch_safe_job_events(
            session,
            "physical-001",
            last_event_id="physical-event-aaaaaaaaaaaa",
        )

    assert [event.event_id for event in events] == ["physical-event-bbbbbbbbbbbb"]
    encoded = encode_sse(events[0])
    assert "Last-Event-ID" not in encoded
    assert "private-operator" not in encoded
    assert "never-export" not in encoded
    assert "/secret/path" not in encoded
    assert "payload_sha256" in encoded


def test_sse_api_supports_last_event_id_without_sensitive_payload(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        rarelink_physical_mode="isolated-integration",
        rarelink_physical_operator_token="operator-secret",
    )
    session_provider = app.dependency_overrides[get_session]()
    session = next(session_provider)
    try:
        session.add(
            PhysicalFederationJob(
                id="physical-sse-001",
                strategy="fedavg",
                expected_sites_json=json.dumps(EXPECTED_SITES),
                total_rounds=5,
                local_epochs=1,
                quorum_required=3,
                job_directory="coordinator-owned",
            )
        )
        session.add(
            PhysicalControlEvent(
                event_id="physical-event-cccccccccccc",
                action="job.submitted",
                actor="private-operator",
                resource_type="physical-job",
                resource_id="physical-sse-001",
                outcome="accepted",
                payload_json='{"password":"never-export"}',
                previous_hash="3" * 64,
                event_hash="4" * 64,
                algorithm="HMAC-SHA256",
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
    finally:
        session.close()
        session_provider.close()

    response = client.get(
        "/api/physical/events/stream",
        params={"job_id": "physical-sse-001", "follow": "false"},
        headers={"X-RareLink-Operator-Token": "operator-secret"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "physical-event-cccccccccccc" in response.text
    assert "private-operator" not in response.text
    assert "never-export" not in response.text

    resumed = client.get(
        "/api/physical/events/stream",
        params={"job_id": "physical-sse-001", "follow": "false"},
        headers={
            "X-RareLink-Operator-Token": "operator-secret",
            "Last-Event-ID": "physical-event-cccccccccccc",
        },
    )
    assert resumed.status_code == 200
    assert resumed.text == ": rarelink-no-new-events\n\n"
