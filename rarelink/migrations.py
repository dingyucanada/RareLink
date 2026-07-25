"""Small additive SQLite migrations for local and pilot deployments.

Production PostgreSQL migrations remain a P1 deliverable. These fixed
identifier migrations keep existing competition/pilot SQLite databases
forward-compatible without deleting or rewriting user data.
"""

from __future__ import annotations

from sqlalchemy import Engine, inspect

SQLITE_ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "physicalsite": {
        "dataset_fingerprint": "VARCHAR",
    },
    "physicalfederationjob": {
        "dataset_fingerprints_json": "VARCHAR NOT NULL DEFAULT '{}'",
        "contract_sha256": "VARCHAR",
        "proposed_by": "VARCHAR",
        "proposer_roles_json": "VARCHAR NOT NULL DEFAULT '[]'",
        "second_approved_by": "VARCHAR",
        "second_approval_note_sha256": "VARCHAR",
        "second_approved_at": "DATETIME",
    },
}


def migrate_sqlite_schema(engine: Engine) -> list[str]:
    if engine.dialect.name != "sqlite":
        return []
    schema = inspect(engine)
    tables = set(schema.get_table_names())
    applied: list[str] = []
    with engine.begin() as connection:
        for table, columns in SQLITE_ADDITIVE_COLUMNS.items():
            if table not in tables:
                continue
            existing = {column["name"] for column in schema.get_columns(table)}
            for column, definition in columns.items():
                if column in existing:
                    continue
                # Table/column/definition are compile-time constants above, not
                # user input. SQLite lacks a parameterized ADD COLUMN form.
                connection.exec_driver_sql(
                    f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}'
                )
                applied.append(f"{table}.{column}")
    return applied
