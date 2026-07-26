import json
import math
import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from rarelink.privacy.physical_contract import (
    build_physical_dpsgd_contract,
    disabled_physical_privacy_contract,
    validate_physical_privacy_contract,
)
from rarelink.services.physical_controller import (
    JobValidationError,
    PhysicalJobRecord,
    PhysicalJobState,
    validate_exported_job,
)
from rarelink.services.physical_store import (
    PhysicalStoreIntegrityError,
    SqlPhysicalJobStore,
)
from scripts.export_physical_nvflare_job import (
    build_client_train_args,
    build_privacy_contract,
)


def privacy_contract(**overrides: object) -> dict:
    contract = build_physical_dpsgd_contract(
        noise_multiplier=1.2,
        max_grad_norm=1.0,
        delta=1e-5,
        accountant="rdp",
    )
    contract.update(overrides)
    return contract


def exported_job(
    tmp_path: Path,
    *,
    privacy: object = ...,
    name: str = "physical-dpsgd-job",
) -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "meta.json").write_text(
        json.dumps({"name": "rarelink-physical-fedavg-dpsgd"}),
        encoding="utf-8",
    )
    receipt = {
        "schema_version": "rarelink-physical-job-export-v2",
        "strategy": "fedavg_dpsgd",
        "rounds": 5,
        "local_epochs": 1,
        "expected_sites": ["hospital-a", "hospital-b", "hospital-c"],
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
    if privacy is ...:
        receipt["privacy"] = privacy_contract()
    elif privacy is not None:
        receipt["privacy"] = privacy
    (root / "rarelink-job-receipt.json").write_text(
        json.dumps(receipt),
        encoding="utf-8",
    )
    return root


def export_args(strategy: str = "fedavg_dpsgd") -> SimpleNamespace:
    return SimpleNamespace(
        strategy=strategy,
        site_manifest_path="/srv/rarelink/site-data/manifest.json",
        site_data_root_path="/srv/rarelink/site-data",
        site_dataset_receipt_path="/var/lib/rarelink/dataset-receipt.json",
        local_epochs=2,
        fedprox_mu=0.01,
        dp_noise_multiplier=1.2,
        dp_max_grad_norm=1.0,
        dp_delta=1e-5,
        dp_accountant="rdp",
    )


def test_valid_dpsgd_export_is_locked_and_publicly_bounded(tmp_path: Path) -> None:
    bundle = validate_exported_job(exported_job(tmp_path))
    privacy = bundle.privacy_contract

    assert bundle.strategy == "fedavg_dpsgd"
    assert privacy["enabled"] is True
    assert privacy["mechanism"] == "opacus_sample_level_dp_sgd"
    assert privacy["noise_multiplier"] == 1.2
    assert privacy["max_grad_norm"] == 1.0
    assert privacy["delta"] == 1e-5
    assert privacy["accountant"] == "rdp"
    assert privacy["site_epsilon_receipt_required"] is True
    assert privacy["end_to_end_sample_dp_claimed"] is False
    assert "does not by itself" in privacy["claim_boundary"]
    assert bundle.public_receipt()["privacy"] == privacy


@pytest.mark.parametrize(
    "invalid_privacy",
    [
        None,
        {},
        privacy_contract(enabled=False),
        privacy_contract(mechanism="gaussian-looking-string"),
        privacy_contract(accountant="prv"),
        privacy_contract(noise_multiplier=0),
        privacy_contract(noise_multiplier=math.nan),
        privacy_contract(noise_multiplier=math.inf),
        privacy_contract(max_grad_norm=-1),
        privacy_contract(delta=0),
        privacy_contract(delta=0.5),
        privacy_contract(site_epsilon_receipt_required=False),
        privacy_contract(end_to_end_sample_dp_claimed=True),
        privacy_contract(extra_unreviewed_field=True),
    ],
)
def test_dpsgd_export_rejects_missing_abnormal_or_forged_privacy(
    tmp_path: Path,
    invalid_privacy: object,
) -> None:
    with pytest.raises(JobValidationError, match="invalid physical privacy"):
        validate_exported_job(exported_job(tmp_path, privacy=invalid_privacy))


def test_missing_dpsgd_privacy_field_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(JobValidationError, match="invalid physical privacy"):
        validate_exported_job(exported_job(tmp_path, privacy=None))


def test_non_dp_strategy_cannot_smuggle_dpsgd_claim() -> None:
    with pytest.raises(ValueError, match="privacy disabled"):
        validate_physical_privacy_contract("fedavg", privacy_contract())
    assert validate_physical_privacy_contract("fedavg", None) == (
        disabled_physical_privacy_contract()
    )


def test_privacy_parameter_change_changes_exported_bundle_digest(tmp_path: Path) -> None:
    first = validate_exported_job(exported_job(tmp_path, name="first"))
    second = validate_exported_job(
        exported_job(
            tmp_path,
            name="second",
            privacy=build_physical_dpsgd_contract(
                noise_multiplier=1.5,
                max_grad_norm=1.0,
                delta=1e-5,
                accountant="rdp",
            ),
        )
    )
    assert first.bundle_sha256 != second.bundle_sha256


def test_export_train_arguments_propagate_exact_locked_opacus_parameters() -> None:
    args = export_args()
    privacy = build_privacy_contract(args)
    arguments = shlex.split(build_client_train_args(args, privacy))

    assert arguments[arguments.index("--dp-noise-multiplier") + 1] == "1.2"
    assert arguments[arguments.index("--dp-max-grad-norm") + 1] == "1.0"
    assert arguments[arguments.index("--dp-delta") + 1] == "1e-05"
    assert arguments[arguments.index("--dp-accountant") + 1] == "rdp"
    assert "--dp-sgd" in arguments
    assert "--require-local-only-manifest" in arguments

    non_dp_args = export_args("fedavg")
    non_dp_privacy = build_privacy_contract(non_dp_args)
    non_dp_arguments = shlex.split(
        build_client_train_args(non_dp_args, non_dp_privacy)
    )
    assert non_dp_privacy["enabled"] is False
    assert all(not argument.startswith("--dp-") for argument in non_dp_arguments)


def test_sql_store_revalidates_dpsgd_bundle_after_restart(tmp_path: Path) -> None:
    job_directory = exported_job(tmp_path)
    bundle = validate_exported_job(job_directory)
    engine = create_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        store = SqlPhysicalJobStore(session)
        store.save(
            PhysicalJobRecord(
                job_id="physical-dpsgd",
                bundle=bundle,
                state=PhysicalJobState.VALIDATED,
            )
        )
        restored = store.get("physical-dpsgd")
        assert restored is not None
        assert restored.bundle.privacy_contract == bundle.privacy_contract

        receipt_path = job_directory / "rarelink-job-receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["privacy"]["noise_multiplier"] = 2.0
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with pytest.raises(PhysicalStoreIntegrityError, match="digest no longer matches"):
            store.get("physical-dpsgd")
