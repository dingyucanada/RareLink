from collections.abc import Generator
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from rarelink.config import Settings, get_settings
from rarelink.migrations import migrate_sqlite_schema

settings = get_settings()


class DatabaseSchemaError(RuntimeError):
    """Raised when a production database is unsafe to serve."""


def normalize_database_url(database_url: str) -> str:
    """Select psycopg 3 explicitly while preserving SQLAlchemy URL details."""
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def is_sqlite_url(database_url: str) -> bool:
    return database_url.startswith("sqlite")


def validate_database_runtime(runtime_settings: Settings, runtime_database_url: str) -> None:
    if (
        runtime_settings.rarelink_physical_mode == "physical"
        and is_sqlite_url(runtime_database_url)
    ):
        raise DatabaseSchemaError(
            "RARELINK_PHYSICAL_MODE=physical requires PostgreSQL; SQLite is limited "
            "to development and isolated integration."
        )


database_url = normalize_database_url(settings.database_url)
connect_args = {"check_same_thread": False} if is_sqlite_url(database_url) else {}
engine = create_engine(database_url, connect_args=connect_args)


if is_sqlite_url(database_url):

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def alembic_config() -> Config:
    project_root = Path(__file__).resolve().parents[1]
    config = Config(project_root / "alembic.ini")
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def expected_schema_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def verify_production_schema(database_engine: Engine) -> str:
    """Require a single, current Alembic revision before serving production traffic."""
    inspector = inspect(database_engine)
    if "alembic_version" not in inspector.get_table_names():
        raise DatabaseSchemaError(
            "Production database is not Alembic-managed. Run `alembic upgrade head` first."
        )
    with database_engine.connect() as connection:
        revisions = list(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )
    expected = expected_schema_revision()
    if revisions != [expected]:
        current = ",".join(revisions) if revisions else "none"
        raise DatabaseSchemaError(
            f"Production database schema revision is {current}; expected {expected}. "
            "Run `alembic upgrade head` before starting RareLink."
        )
    return expected


def create_db_and_tables() -> None:
    settings.artifact_root.mkdir(parents=True, exist_ok=True)
    validate_database_runtime(settings, database_url)
    if is_sqlite_url(database_url):
        SQLModel.metadata.create_all(engine)
        migrate_sqlite_schema(engine)
        return
    verify_production_schema(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
