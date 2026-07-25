from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from alembic import command
from rarelink.config import Settings
from rarelink.database import (
    DatabaseSchemaError,
    alembic_config,
    expected_schema_revision,
    normalize_database_url,
    validate_database_runtime,
    verify_production_schema,
)


def test_normalize_database_url_uses_psycopg3() -> None:
    assert (
        normalize_database_url("postgresql://user:secret@db/rarelink?sslmode=require")
        == "postgresql+psycopg://user:secret@db/rarelink?sslmode=require"
    )
    assert normalize_database_url("postgres://db/rarelink") == (
        "postgresql+psycopg://db/rarelink"
    )
    assert normalize_database_url("sqlite:///rarelink.db") == "sqlite:///rarelink.db"


def test_physical_mode_rejects_sqlite() -> None:
    settings = Settings(_env_file=None, rarelink_physical_mode="physical")
    with pytest.raises(DatabaseSchemaError, match="requires PostgreSQL"):
        validate_database_runtime(settings, "sqlite:///pilot.db")


def test_isolated_integration_allows_sqlite() -> None:
    settings = Settings(_env_file=None, rarelink_physical_mode="isolated-integration")
    validate_database_runtime(settings, "sqlite:///pilot.db")


def test_schema_check_rejects_unmanaged_database(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'unmanaged.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE example (id INTEGER PRIMARY KEY)"))

    with pytest.raises(DatabaseSchemaError, match="not Alembic-managed"):
        verify_production_schema(engine)


def test_schema_check_rejects_stale_revision(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'stale.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES ('stale-revision')")
        )

    with pytest.raises(DatabaseSchemaError, match="stale-revision"):
        verify_production_schema(engine)


def test_schema_check_accepts_alembic_head(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "managed.db"
    monkeypatch.setenv("RARELINK_DATABASE_URL", f"sqlite:///{database_path}")
    config = alembic_config()
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    assert verify_production_schema(engine) == expected_schema_revision()
