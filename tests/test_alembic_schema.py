from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlmodel import SQLModel

import rarelink.models  # noqa: F401
from alembic import command

EXPECTED_KEY_COLUMNS = {
    "study": {"id", "title", "status", "created_at", "updated_at"},
    "experiment": {"id", "study_id", "strategy", "status", "metrics_json"},
    "auditevent": {"id", "study_id", "event_type", "actor", "payload_json"},
    "agentartifact": {"id", "study_id", "role", "artifact_type", "source"},
    "trainingjob": {
        "id",
        "study_id",
        "experiment_id",
        "status",
        "global_model_path",
    },
    "physicalsite": {
        "site_id",
        "organization",
        "status",
        "dataset_fingerprint",
        "last_heartbeat_at",
    },
    "physicalheartbeatreceipt": {
        "heartbeat_id",
        "site_id",
        "payload_sha256",
        "captured_at",
    },
    "physicalcontrolevent": {
        "id",
        "event_id",
        "action",
        "actor",
        "previous_hash",
        "event_hash",
    },
    "physicalfederationjob": {
        "id",
        "external_job_id",
        "bundle_sha256",
        "contract_sha256",
        "dataset_fingerprints_json",
        "proposed_by",
        "second_approved_by",
        "second_approval_expires_at",
        "global_model_sha256",
    },
    "physicaljobapprovalrecord": {
        "id",
        "job_id",
        "contract_sha256",
        "approver_subject_id",
        "note_sha256",
        "expires_at",
    },
}


def alembic_config() -> Config:
    root = Path(__file__).resolve().parents[1]
    return Config(str(root / "alembic.ini"))


def test_initial_schema_upgrades_and_downgrades_temporary_sqlite(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "migration-test.sqlite3"
    database_url = f"sqlite:///{database}"
    monkeypatch.setenv("RARELINK_DATABASE_URL", database_url)

    config = alembic_config()
    command.upgrade(config, "head")
    command.check(config)

    engine = create_engine(database_url)
    inspector = inspect(engine)
    application_tables = set(inspector.get_table_names()) - {"alembic_version"}
    assert application_tables == set(SQLModel.metadata.tables)
    for table_name, required_columns in EXPECTED_KEY_COLUMNS.items():
        actual_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        model_columns = {
            column.name for column in SQLModel.metadata.tables[table_name].columns
        }
        assert actual_columns == model_columns
        assert required_columns <= actual_columns

    approval_indexes = {
        index["name"]: index for index in inspector.get_indexes("physicaljobapprovalrecord")
    }
    assert approval_indexes["ix_physicaljobapprovalrecord_job_id"]["unique"] == 1
    assert {
        foreign_key["referred_table"]
        for foreign_key in inspector.get_foreign_keys("physicaljobapprovalrecord")
    } == {"physicalfederationjob"}
    assert {
        foreign_key["referred_table"]
        for foreign_key in inspector.get_foreign_keys("trainingjob")
    } == {"study", "experiment"}
    engine.dispose()

    command.downgrade(config, "base")
    downgraded_engine = create_engine(database_url)
    assert set(inspect(downgraded_engine).get_table_names()) == {"alembic_version"}
    downgraded_engine.dispose()


def test_offline_migration_output_never_prints_database_password(
    monkeypatch,
    capsys,
) -> None:
    password = "super-secret-migration-password"
    monkeypatch.setenv(
        "RARELINK_DATABASE_URL",
        f"postgresql://rarelink:{password}@db.internal.example/rarelink",
    )
    command.upgrade(alembic_config(), "head", sql=True)
    captured = capsys.readouterr()
    assert password not in captured.out
    assert password not in captured.err
