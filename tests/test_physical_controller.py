import json
from pathlib import Path

import pytest

from rarelink.services.physical_controller import (
    CommandResult,
    InMemoryPhysicalJobStore,
    JobConflictError,
    JobValidationError,
    NvflareCliAdapter,
    NvflareCliError,
    PhysicalFederationController,
    PhysicalJobState,
    calculate_three_site_quorum,
    parse_external_job_id,
    sha256_file,
    validate_exported_job,
)


def exported_job(tmp_path: Path, **receipt_overrides: object) -> Path:
    root = tmp_path / "rarelink-fedavg-job"
    root.mkdir()
    (root / "meta.json").write_text(
        json.dumps({"name": "rarelink-physical-fedavg", "deploy_map": {}}),
        encoding="utf-8",
    )
    (root / "app.json").write_text(json.dumps({"format_version": 2}), encoding="utf-8")
    receipt = {
        "schema_version": "rarelink-physical-job-export-v1",
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
    receipt.update(receipt_overrides)
    (root / "rarelink-job-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    return root


class ScriptedRunner:
    def __init__(self, results: list[CommandResult]):
        self.results = list(results)
        self.commands: list[list[str]] = []

    def __call__(self, command):  # type: ignore[no-untyped-def]
        self.commands.append(list(command))
        return self.results.pop(0)


def controller_with_runner(runner: ScriptedRunner) -> PhysicalFederationController:
    return PhysicalFederationController(
        NvflareCliAdapter(runner=runner),
        InMemoryPhysicalJobStore(),
    )


def serialized(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def test_export_validation_builds_safe_deterministic_receipt(tmp_path: Path) -> None:
    job = exported_job(tmp_path)
    first = validate_exported_job(job)
    second = validate_exported_job(job)

    assert first.bundle_sha256 == second.bundle_sha256
    assert len(first.bundle_sha256) == 64
    assert first.expected_sites == ("hospital-a", "hospital-b", "hospital-c")
    receipt = first.public_receipt()
    assert receipt["job_directory_name"] == job.name
    assert receipt["patient_data_packaged"] is False
    assert str(tmp_path) not in serialized(receipt)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"expected_sites": ["hospital-a", "hospital-b"]}, "exactly three"),
        ({"expected_sites": ["hospital-a", "hospital-a", "hospital-c"]}, "distinct"),
        ({"rounds": 0}, "positive integer"),
        ({"patient_data_packaged": True}, "prove data"),
        ({"private_keys_packaged": True}, "prove data"),
        ({"local_only_manifest_required": False}, "local-only"),
        ({"dataset_receipt_required": False}, "dataset receipt"),
    ],
)
def test_export_validation_rejects_unsafe_or_invalid_contract(
    tmp_path: Path,
    override: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(JobValidationError, match=message):
        validate_exported_job(exported_job(tmp_path, **override))


def test_export_validation_rejects_patient_image_and_private_key(tmp_path: Path) -> None:
    job = exported_job(tmp_path)
    (job / "patient-001.nii.gz").write_bytes(b"not an image")
    with pytest.raises(JobValidationError, match="patient-level"):
        validate_exported_job(job)

    (job / "patient-001.nii.gz").unlink()
    (job / "client.key").write_text("private", encoding="utf-8")
    with pytest.raises(JobValidationError, match="Sensitive"):
        validate_exported_job(job)


def test_export_validation_rejects_sensitive_json_fields(tmp_path: Path) -> None:
    job = exported_job(tmp_path)
    (job / "meta.json").write_text(
        json.dumps({"patient_id": "pediatric-case-001"}),
        encoding="utf-8",
    )
    with pytest.raises(JobValidationError, match="patient_id"):
        validate_exported_job(job)


def test_job_id_parser_supports_json_and_prose_but_rejects_missing_id() -> None:
    assert parse_external_job_id('{"result":{"job_id":"01J-FLARE-ABC"}}') == "01J-FLARE-ABC"
    assert parse_external_job_id("Job ID: flare-job-2026") == "flare-job-2026"
    with pytest.raises(NvflareCliError):
        parse_external_job_id("submission accepted without an identifier")


def test_adapter_submit_parses_prose_output_without_exposing_raw_output(
    tmp_path: Path,
) -> None:
    runner = ScriptedRunner(
        [CommandResult(0, "NVFLARE accepted request\nJob ID: flare-prose-2026")]
    )
    adapter = NvflareCliAdapter(runner=runner)
    result = adapter.submit(tmp_path / "job", tmp_path / "private-admin-kit")

    assert result.external_job_id == "flare-prose-2026"
    receipt = serialized(result.public_receipt())
    assert "private-admin-kit" not in receipt
    assert "NVFLARE accepted" not in receipt


def test_adapter_uses_nvflare_27_job_cli_command_shapes(tmp_path: Path) -> None:
    runner = ScriptedRunner(
        [
            CommandResult(0, '{"job_id":"flare-cli-shape"}'),
            CommandResult(0, '{"status":"RUNNING"}'),
            CommandResult(0, "[]"),
            CommandResult(0, '{"status":"ABORTED"}'),
        ]
    )
    adapter = NvflareCliAdapter(runner=runner)
    job = tmp_path / "exported-job"
    admin = tmp_path / "admin-kit"

    adapter.submit(job, admin)
    adapter.status("flare-cli-shape", admin)
    adapter.list_jobs(admin)
    adapter.abort("flare-cli-shape", admin)

    assert runner.commands == [
        [
            "nvflare",
            "job",
            "submit",
            "-j",
            str(job.resolve()),
            "--startup-kit",
            str(admin.resolve()),
        ],
        [
            "nvflare",
            "job",
            "meta",
            "flare-cli-shape",
            "--startup-kit",
            str(admin.resolve()),
        ],
        [
            "nvflare",
            "job",
            "list",
            "--startup-kit",
            str(admin.resolve()),
        ],
        [
            "nvflare",
            "job",
            "abort",
            "flare-cli-shape",
            "--startup-kit",
            str(admin.resolve()),
        ],
    ]


def test_submit_persists_external_id_and_is_idempotent(tmp_path: Path) -> None:
    runner = ScriptedRunner(
        [CommandResult(0, '{"job_id":"flare-job-001","status":"SUBMITTED"}')]
    )
    controller = controller_with_runner(runner)
    register = controller.register("physical-001", exported_job(tmp_path))
    assert register["state"] == PhysicalJobState.VALIDATED

    first = controller.submit(
        "physical-001",
        admin_kit=tmp_path / "admin-secret-kit",
        submit_token="same-token-2026",
    )
    second = controller.submit(
        "physical-001",
        admin_kit=tmp_path / "admin-secret-kit",
        submit_token="same-token-2026",
    )

    assert first["external_job_id"] == "flare-job-001"
    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert len(runner.commands) == 1
    assert "same-token-2026" not in " ".join(runner.commands[0])
    public = serialized([first, second, controller.list()])
    assert str(tmp_path / "admin-secret-kit") not in public
    assert "same-token-2026" not in public

    with pytest.raises(JobConflictError, match="different idempotency token"):
        controller.submit(
            "physical-001",
            admin_kit=tmp_path / "admin-secret-kit",
            submit_token="other-token-2026",
        )


def test_status_updates_round_and_requires_signed_three_site_quorum(tmp_path: Path) -> None:
    runner = ScriptedRunner(
        [
            CommandResult(0, '{"job_id":"flare-job-002"}'),
            CommandResult(
                0,
                json.dumps(
                    {
                        "status": "RUNNING",
                        "current_round": 2,
                        "received_from": ["hospital-a", "hospital-b"],
                        "received_updates": 2,
                        "patient_name": "must-not-be-relayed",
                    }
                ),
            ),
            CommandResult(
                0,
                json.dumps(
                    {
                        "status": "COMPLETED",
                        "current_round": 5,
                        "received_from": ["hospital-a", "hospital-b", "hospital-c"],
                        "received_updates": 3,
                    }
                ),
            ),
        ]
    )
    controller = controller_with_runner(runner)
    controller.register("physical-002", exported_job(tmp_path))
    controller.submit(
        "physical-002",
        admin_kit=tmp_path / "admin-kit",
        submit_token="submit-token-002",
    )

    running = controller.status("physical-002", admin_kit=tmp_path / "admin-kit")
    assert running["state"] == PhysicalJobState.RUNNING
    assert running["current_round"] == 2
    assert running["quorum"]["received_updates"] == 2
    assert running["quorum"]["satisfied"] is False
    assert running["quorum"]["missing_sites"] == ["hospital-c"]
    assert "must-not-be-relayed" not in serialized(running)

    complete = controller.status("physical-002", admin_kit=tmp_path / "admin-kit")
    assert complete["state"] == PhysicalJobState.COMPLETED
    assert complete["quorum"]["satisfied"] is True


def test_numeric_update_count_cannot_forge_site_quorum() -> None:
    quorum = calculate_three_site_quorum(
        ["hospital-a", "hospital-b", "hospital-c"],
        ["hospital-a", "attacker-site"],
        received_updates=99,
    )
    assert quorum.satisfied is False
    assert quorum.missing_sites == ("hospital-b", "hospital-c")
    assert quorum.unexpected_sites == ("attacker-site",)


def test_remote_completion_without_three_site_identities_is_failed_closed(
    tmp_path: Path,
) -> None:
    runner = ScriptedRunner(
        [
            CommandResult(0, '{"job_id":"flare-incomplete"}'),
            CommandResult(
                0,
                '{"status":"COMPLETED","current_round":5,'
                '"received_from":["hospital-a","hospital-b"],"received_updates":3}',
            ),
        ]
    )
    controller = controller_with_runner(runner)
    controller.register("physical-incomplete", exported_job(tmp_path))
    controller.submit(
        "physical-incomplete",
        admin_kit=tmp_path / "admin-kit",
        submit_token="incomplete-token",
    )
    receipt = controller.status(
        "physical-incomplete",
        admin_kit=tmp_path / "admin-kit",
    )

    assert receipt["state"] == PhysicalJobState.FAILED
    assert receipt["error_code"] == "INCOMPLETE_THREE_SITE_QUORUM"
    assert receipt["quorum"]["satisfied"] is False


def test_abort_is_idempotent_and_does_not_relay_cli_payload(tmp_path: Path) -> None:
    runner = ScriptedRunner(
        [
            CommandResult(0, '{"job_id":"flare-job-003"}'),
            CommandResult(0, '{"status":"ABORTED","secret":"never relay this"}'),
        ]
    )
    controller = controller_with_runner(runner)
    controller.register("physical-003", exported_job(tmp_path))
    controller.submit(
        "physical-003",
        admin_kit=tmp_path / "admin-kit",
        submit_token="submit-token-003",
    )
    first = controller.abort("physical-003", admin_kit=tmp_path / "admin-kit")
    second = controller.abort("physical-003", admin_kit=tmp_path / "admin-kit")
    assert first["state"] == PhysicalJobState.ABORTED
    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert len(runner.commands) == 2
    assert "never relay this" not in serialized(first)


def test_retry_creates_new_external_attempt_and_resume_reattaches(tmp_path: Path) -> None:
    runner = ScriptedRunner(
        [
            CommandResult(0, '{"job_id":"flare-job-old"}'),
            CommandResult(0, '{"status":"FAILED"}'),
            CommandResult(0, '{"job_id":"flare-job-new"}'),
            CommandResult(
                0,
                '{"status":"RUNNING","current_round":1,'
                '"received_from":["hospital-a"],"received_updates":1}',
            ),
        ]
    )
    controller = controller_with_runner(runner)
    controller.register("physical-retry", exported_job(tmp_path))
    controller.submit(
        "physical-retry",
        admin_kit=tmp_path / "admin-kit",
        submit_token="first-token-2026",
    )
    failed = controller.status("physical-retry", admin_kit=tmp_path / "admin-kit")
    assert failed["state"] == PhysicalJobState.FAILED

    retried = controller.retry(
        "physical-retry",
        admin_kit=tmp_path / "admin-kit",
        submit_token="retry-token-2026",
    )
    assert retried["external_job_id"] == "flare-job-new"
    assert retried["attempt"] == 2
    assert retried["retry"] is True

    resumed = controller.resume(
        "physical-retry",
        admin_kit=tmp_path / "admin-kit",
        submit_token="unused-while-active",
    )
    assert resumed["reattached"] is True
    assert resumed["state"] == PhysicalJobState.RUNNING
    assert len(runner.commands) == 4


def test_remote_list_returns_only_count_and_managed_safe_receipts(tmp_path: Path) -> None:
    runner = ScriptedRunner(
        [
            CommandResult(
                0,
                '[{"job_id":"one","patient_id":"x"},{"job_id":"two","secret":"y"}]',
            )
        ]
    )
    controller = controller_with_runner(runner)
    controller.register("local-only", exported_job(tmp_path))
    receipt = controller.list_remote(admin_kit=tmp_path / "sensitive-admin-kit")
    assert receipt["remote_job_count"] == 2
    payload = serialized(receipt)
    assert "patient_id" not in payload
    assert '"secret": "y"' not in payload
    assert str(tmp_path) not in payload


def test_global_model_sha256_must_match_and_public_receipt_hides_path(tmp_path: Path) -> None:
    runner = ScriptedRunner(
        [
            CommandResult(0, '{"job_id":"flare-job-model"}'),
            CommandResult(
                0,
                '{"status":"COMPLETED","current_round":5,'
                '"received_from":["hospital-a","hospital-b","hospital-c"],'
                '"received_updates":3}',
            ),
        ]
    )
    controller = controller_with_runner(runner)
    controller.register("physical-model", exported_job(tmp_path))
    controller.submit(
        "physical-model",
        admin_kit=tmp_path / "admin-kit",
        submit_token="model-token-2026",
    )
    controller.status("physical-model", admin_kit=tmp_path / "admin-kit")
    model = tmp_path / "coordinator-artifacts" / "rarelink-global.pt"
    model.parent.mkdir()
    model.write_bytes(b"trusted global model bytes")
    expected = sha256_file(model)

    with pytest.raises(JobValidationError, match="does not match"):
        controller.verify_global_model(
            "physical-model",
            model,
            expected_sha256="0" * 64,
        )
    receipt = controller.verify_global_model(
        "physical-model",
        model,
        expected_sha256=expected,
    )
    assert receipt["verified"] is True
    assert receipt["global_model_sha256"] == expected
    assert receipt["model_file_name"] == model.name
    assert str(model.parent) not in serialized(receipt)


def test_failed_cli_exposes_only_operation_exit_code_and_output_hash(tmp_path: Path) -> None:
    runner = ScriptedRunner(
        [CommandResult(7, "", "password=secret patient_name=hidden /admin/kit")]
    )
    controller = controller_with_runner(runner)
    controller.register("physical-fail", exported_job(tmp_path))
    with pytest.raises(NvflareCliError) as captured:
        controller.submit(
            "physical-fail",
            admin_kit=tmp_path / "admin-kit",
            submit_token="failure-token",
        )
    message = str(captured.value)
    assert "password" not in message
    assert "patient_name" not in message
    assert "/admin/kit" not in message
    assert "sha256=" in message
