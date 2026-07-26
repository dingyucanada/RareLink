import json
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from rarelink.models import PhysicalFederationJob
from rarelink.services.physical_controller import (
    CommandResult,
    InMemoryPhysicalJobStore,
    JobConflictError,
    NvflareCliAdapter,
    NvflareCliError,
    PhysicalFederationController,
    PhysicalJobState,
)
from rarelink.services.physical_store import (
    PhysicalStoreIntegrityError,
    SqlPhysicalJobStore,
)


class QueueRunner:
    def __init__(self):
        self.results: list[CommandResult] = []
        self.commands: list[list[str]] = []

    def __call__(self, command):  # type: ignore[no-untyped-def]
        self.commands.append(list(command))
        if not self.results:
            raise AssertionError("Unexpected external CLI invocation")
        return self.results.pop(0)


def exported_job(tmp_path: Path, name: str = "job") -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "meta.json").write_text(
        json.dumps({"name": "rarelink-physical-fedavg"}),
        encoding="utf-8",
    )
    (root / "rarelink-job-receipt.json").write_text(
        json.dumps(
            {
                "strategy": "fedavg",
                "rounds": 5,
                "local_epochs": 1,
                "expected_sites": ["hospital-a", "hospital-b", "hospital-c"],
                "local_only_manifest_required": True,
                "dataset_receipt_required": True,
                "patient_data_packaged": False,
                "certificates_packaged": False,
                "private_keys_packaged": False,
            }
        ),
        encoding="utf-8",
    )
    return root


def make_controller(
    runner: QueueRunner,
    store=None,  # type: ignore[no-untyped-def]
) -> PhysicalFederationController:
    return PhysicalFederationController(
        NvflareCliAdapter(runner=runner),
        store or InMemoryPhysicalJobStore(),
    )


def submit_job(
    controller: PhysicalFederationController,
    runner: QueueRunner,
    tmp_path: Path,
    job_id: str = "physical-reconcile",
) -> None:
    controller.register(job_id, exported_job(tmp_path))
    runner.results.append(CommandResult(0, '{"job_id":"flare-reconcile"}'))
    controller.submit(
        job_id,
        admin_kit=tmp_path / "admin-kit",
        submit_token=f"token-{job_id}",
    )


def test_unknown_remote_state_fails_closed_and_later_valid_snapshot_recovers(
    tmp_path: Path,
) -> None:
    runner = QueueRunner()
    controller = make_controller(runner)
    submit_job(controller, runner, tmp_path)
    runner.results.extend(
        [
            CommandResult(0, '{"status":"ALIEN_STATE"}'),
            CommandResult(
                0,
                '{"status":"RUNNING","current_round":1,'
                '"received_from":["hospital-a"],"received_updates":1}',
            ),
        ]
    )

    failed = controller.status(
        "physical-reconcile",
        admin_kit=tmp_path / "admin-kit",
    )
    assert failed["state"] == PhysicalJobState.FAILED
    assert failed["error_code"] == "RECONCILIATION_UNKNOWN_REMOTE_STATE"
    assert failed["reconciliation"]["failed_closed"] is True

    recovered = controller.status(
        "physical-reconcile",
        admin_kit=tmp_path / "admin-kit",
    )
    assert recovered["state"] == PhysicalJobState.RUNNING
    assert recovered["error_code"] is None
    assert recovered["current_round"] == 1


def test_wrapped_nvflare_terminal_status_is_reconciled_strictly(
    tmp_path: Path,
) -> None:
    runner = QueueRunner()
    controller = make_controller(runner)
    submit_job(controller, runner, tmp_path)
    runner.results.append(
        CommandResult(
            0,
            '{"result":{"job_id":"flare-reconcile",'
            '"status":"FINISHED:COMPLETED","current_round":5,'
            '"received_from":["hospital-a","hospital-b","hospital-c"],'
            '"received_updates":3}}',
        )
    )
    receipt = controller.status(
        "physical-reconcile",
        admin_kit=tmp_path / "admin-kit",
    )
    assert receipt["state"] == PhysicalJobState.COMPLETED
    assert receipt["reconciliation"]["outcome"] == "COMPLETION_VERIFIED"


@pytest.mark.parametrize(
    "payload",
    [
        "[]",
        "{}",
        '{"status":42}',
        '{"status":"RUNNING"}',
        '{"status":"RUNNING","current_round":6}',
        (
            '{"status":"RUNNING","current_round":1,'
            '"received_from":["hospital-a","hospital-a"],"received_updates":2}'
        ),
        (
            '{"status":"RUNNING","current_round":1,'
            '"received_from":["hospital-a","hospital-x"],"received_updates":2}'
        ),
        (
            '{"status":"RUNNING","current_round":1,'
            '"received_from":["hospital-a"],"received_updates":2}'
        ),
    ],
)
def test_invalid_remote_metadata_is_never_treated_as_running(
    tmp_path: Path,
    payload: str,
) -> None:
    runner = QueueRunner()
    controller = make_controller(runner)
    submit_job(controller, runner, tmp_path)
    runner.results.append(CommandResult(0, payload))

    receipt = controller.status(
        "physical-reconcile",
        admin_kit=tmp_path / "admin-kit",
    )
    assert receipt["state"] == PhysicalJobState.FAILED
    assert receipt["reconciliation"]["failed_closed"] is True
    assert receipt["error_code"]


def test_illegal_state_regression_fails_closed(tmp_path: Path) -> None:
    runner = QueueRunner()
    controller = make_controller(runner)
    submit_job(controller, runner, tmp_path)
    runner.results.extend(
        [
            CommandResult(
                0,
                '{"status":"RUNNING","current_round":2,'
                '"received_from":["hospital-a"],"received_updates":1}',
            ),
            CommandResult(0, '{"status":"SUBMITTED","current_round":2}'),
        ]
    )
    controller.status("physical-reconcile", admin_kit=tmp_path / "admin-kit")
    regressed = controller.status(
        "physical-reconcile",
        admin_kit=tmp_path / "admin-kit",
    )
    assert regressed["state"] == PhysicalJobState.FAILED
    assert regressed["error_code"] == "RECONCILIATION_ILLEGAL_STATE_REGRESSION"


def test_late_round_snapshot_is_ignored_without_regressing_quorum(
    tmp_path: Path,
) -> None:
    runner = QueueRunner()
    controller = make_controller(runner)
    submit_job(controller, runner, tmp_path)
    runner.results.extend(
        [
            CommandResult(
                0,
                '{"status":"RUNNING","current_round":3,'
                '"received_from":["hospital-a","hospital-b"],"received_updates":2}',
            ),
            CommandResult(
                0,
                '{"status":"RUNNING","current_round":2,'
                '"received_from":["hospital-a","hospital-b","hospital-c"],'
                '"received_updates":3}',
            ),
        ]
    )
    current = controller.status(
        "physical-reconcile",
        admin_kit=tmp_path / "admin-kit",
    )
    late = controller.status(
        "physical-reconcile",
        admin_kit=tmp_path / "admin-kit",
    )
    assert current["current_round"] == 3
    assert late["current_round"] == 3
    assert late["quorum"]["reported_sites"] == ["hospital-a", "hospital-b"]
    assert late["reconciliation"]["late_snapshot_ignored"] is True
    assert late["reconciliation"]["outcome"] == "LATE_ROUND_SNAPSHOT_IGNORED"


def test_same_round_stale_snapshot_is_merged_idempotently(tmp_path: Path) -> None:
    runner = QueueRunner()
    controller = make_controller(runner)
    submit_job(controller, runner, tmp_path)
    runner.results.extend(
        [
            CommandResult(
                0,
                '{"status":"RUNNING","current_round":2,'
                '"received_from":["hospital-a","hospital-b"],"received_updates":2}',
            ),
            CommandResult(
                0,
                '{"status":"RUNNING","current_round":2,'
                '"received_from":["hospital-a"],"received_updates":1}',
            ),
        ]
    )
    controller.status("physical-reconcile", admin_kit=tmp_path / "admin-kit")
    stale = controller.status(
        "physical-reconcile",
        admin_kit=tmp_path / "admin-kit",
    )
    assert stale["quorum"]["reported_sites"] == ["hospital-a", "hospital-b"]
    assert stale["quorum"]["received_updates"] == 2
    assert stale["reconciliation"]["outcome"] == "STALE_SAME_ROUND_SNAPSHOT_MERGED"


def test_explicit_site_dropout_waits_for_all_sites_and_can_recover(
    tmp_path: Path,
) -> None:
    runner = QueueRunner()
    controller = make_controller(runner)
    submit_job(controller, runner, tmp_path)
    runner.results.extend(
        [
            CommandResult(
                0,
                '{"status":"RUNNING","current_round":2,'
                '"connected_clients":["hospital-a","hospital-b"],'
                '"received_from":["hospital-a"],"received_updates":1}',
            ),
            CommandResult(
                0,
                '{"status":"RUNNING","current_round":2,'
                '"connected_clients":["hospital-a","hospital-b","hospital-c"],'
                '"received_from":["hospital-a","hospital-b"],"received_updates":2}',
            ),
        ]
    )
    degraded = controller.status(
        "physical-reconcile",
        admin_kit=tmp_path / "admin-kit",
    )
    assert degraded["state"] == PhysicalJobState.WAITING_FOR_SITES
    assert degraded["error_code"] == "EXPECTED_SITE_OFFLINE"
    assert degraded["reconciliation"]["site_dropout"] is True

    recovered = controller.status(
        "physical-reconcile",
        admin_kit=tmp_path / "admin-kit",
    )
    assert recovered["state"] == PhysicalJobState.RUNNING
    assert recovered["error_code"] is None
    assert recovered["quorum"]["satisfied"] is False


def test_submit_intent_survives_unknown_outcome_and_blocks_resubmit(
    tmp_path: Path,
) -> None:
    runner = QueueRunner()
    store = InMemoryPhysicalJobStore()
    controller = make_controller(runner, store)
    registration = controller.register(
        "physical-unknown-submit",
        exported_job(tmp_path),
    )
    runner.results.append(CommandResult(0, "accepted without a job identifier"))

    with pytest.raises(NvflareCliError):
        controller.submit(
            "physical-unknown-submit",
            admin_kit=tmp_path / "admin-kit",
            submit_token="stable-submit-token",
        )
    assert len(runner.commands) == 1

    restarted = make_controller(runner, store)
    repeated = restarted.submit(
        "physical-unknown-submit",
        admin_kit=tmp_path / "admin-kit",
        submit_token="stable-submit-token",
    )
    assert repeated["requires_reconciliation"] is True
    assert repeated["idempotent"] is True
    assert len(runner.commands) == 1

    runner.results.append(
        CommandResult(
            0,
            json.dumps(
                [
                    {
                        "job_id": "flare-recovered",
                        "metadata": {
                            "bundle_sha256": registration["bundle_sha256"],
                        },
                    }
                ]
            ),
        )
    )
    reconciled = restarted.reconcile_submission(
        "physical-unknown-submit",
        admin_kit=tmp_path / "admin-kit",
    )
    assert reconciled["external_job_id"] == "flare-recovered"
    assert reconciled["reconciliation"]["resolved"] is True
    assert sum(command[2] == "submit" for command in runner.commands) == 1


def test_absent_submission_match_never_triggers_automatic_resubmit(
    tmp_path: Path,
) -> None:
    runner = QueueRunner()
    store = InMemoryPhysicalJobStore()
    controller = make_controller(runner, store)
    controller.register("physical-unknown-submit", exported_job(tmp_path))
    runner.results.append(CommandResult(0, "accepted without a job identifier"))
    with pytest.raises(NvflareCliError):
        controller.submit(
            "physical-unknown-submit",
            admin_kit=tmp_path / "admin-kit",
            submit_token="stable-submit-token",
        )
    runner.results.append(CommandResult(0, "[]"))

    receipt = controller.reconcile_submission(
        "physical-unknown-submit",
        admin_kit=tmp_path / "admin-kit",
    )
    assert receipt["external_job_id"] is None
    assert receipt["error_code"] == "SUBMIT_OUTCOME_UNKNOWN"
    assert receipt["reconciliation"]["resolved"] is False
    assert sum(command[2] == "submit" for command in runner.commands) == 1


def test_submit_token_cannot_be_reused_for_another_job(tmp_path: Path) -> None:
    runner = QueueRunner()
    controller = make_controller(runner)
    controller.register("physical-one", exported_job(tmp_path, "job-one"))
    controller.register("physical-two", exported_job(tmp_path, "job-two"))
    runner.results.append(CommandResult(0, '{"job_id":"flare-one"}'))
    controller.submit(
        "physical-one",
        admin_kit=tmp_path / "admin-kit",
        submit_token="cross-job-token",
    )
    with pytest.raises(JobConflictError, match="another physical job"):
        controller.submit(
            "physical-two",
            admin_kit=tmp_path / "admin-kit",
            submit_token="cross-job-token",
        )
    assert len(runner.commands) == 1


def test_restart_recovery_uses_persisted_external_id_without_resubmitting(
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    runner = QueueRunner()
    with Session(engine) as session:
        first_store = SqlPhysicalJobStore(session)
        first = make_controller(runner, first_store)
        first.register("physical-persisted", exported_job(tmp_path))
        runner.results.append(CommandResult(0, '{"job_id":"flare-persisted"}'))
        first.submit(
            "physical-persisted",
            admin_kit=tmp_path / "admin-kit",
            submit_token="persisted-token",
        )

        restarted = make_controller(runner, SqlPhysicalJobStore(session))
        runner.results.append(
            CommandResult(
                0,
                '{"status":"RUNNING","current_round":1,'
                '"received_from":["hospital-a"],"received_updates":1}',
            )
        )
        receipt = restarted.recover_after_restart(
            admin_kit=tmp_path / "admin-kit",
        )
        assert receipt["checked_jobs"] == 1
        assert receipt["external_submit_performed"] is False
        assert receipt["evidence_scope"] == "control-protocol-only"
        assert sum(command[2] == "submit" for command in runner.commands) == 1


def test_sql_store_rejects_corrupt_persisted_recovery_state(tmp_path: Path) -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            PhysicalFederationJob(
                id="physical-corrupt",
                strategy="fedavg",
                bundle_sha256="a" * 64,
                expected_sites_json='["hospital-a","hospital-a","hospital-c"]',
                connected_sites_json="[]",
                dataset_fingerprints_json="{}",
                total_rounds=5,
                local_epochs=1,
                quorum_required=3,
                job_directory=str(tmp_path / "job"),
            )
        )
        session.commit()
        with pytest.raises(PhysicalStoreIntegrityError, match="expected_sites_json"):
            SqlPhysicalJobStore(session).get("physical-corrupt")
