from sqlalchemy import inspect
from sqlmodel import create_engine

from rarelink.migrations import migrate_sqlite_schema


def test_additive_sqlite_migration_upgrades_existing_physical_tables(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite3'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE physicalsite (
                site_id VARCHAR PRIMARY KEY,
                display_name VARCHAR NOT NULL,
                organization VARCHAR NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE physicalfederationjob (
                id VARCHAR PRIMARY KEY,
                strategy VARCHAR NOT NULL,
                expected_sites_json VARCHAR NOT NULL
            )
            """
        )

    first = migrate_sqlite_schema(engine)
    second = migrate_sqlite_schema(engine)
    schema = inspect(engine)
    site_columns = {column["name"] for column in schema.get_columns("physicalsite")}
    job_columns = {
        column["name"] for column in schema.get_columns("physicalfederationjob")
    }

    assert first == [
        "physicalsite.dataset_fingerprint",
        "physicalfederationjob.dataset_fingerprints_json",
    ]
    assert second == []
    assert "dataset_fingerprint" in site_columns
    assert "dataset_fingerprints_json" in job_columns
