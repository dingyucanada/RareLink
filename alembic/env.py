"""Alembic environment for RareLink's SQLModel schema."""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

# Importing models registers every SQLModel table on the shared metadata. It does
# not import rarelink.database, create an engine, or read application secrets.
import rarelink.models  # noqa: F401
from alembic import context

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = SQLModel.metadata


def database_url() -> str:
    value = os.environ.get("RARELINK_DATABASE_URL")
    if not value:
        raise RuntimeError("RARELINK_DATABASE_URL is required for database migrations")
    return value


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    # This is a detached dictionary returned by Alembic, so assigning directly
    # avoids ConfigParser interpolation and preserves percent-encoded credentials.
    section["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
