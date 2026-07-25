#!/usr/bin/env python3
"""Fail closed unless the configured production database is at Alembic head."""

from rarelink.database import engine, verify_production_schema


def main() -> None:
    revision = verify_production_schema(engine)
    print(f"RareLink database schema verified at revision {revision}")


if __name__ == "__main__":
    main()
