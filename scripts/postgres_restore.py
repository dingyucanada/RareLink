#!/usr/bin/env python3
"""Restore and verify a RareLink PostgreSQL backup."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rarelink.database import expected_schema_revision
from rarelink.operations.postgres_backup import restore_backup


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--target-service", required=True)
    parser.add_argument("--confirm-target-service", required=True)
    parser.add_argument("--expected-revision", default=expected_schema_revision())
    args = parser.parse_args()
    receipt = restore_backup(
        backup_path=args.backup,
        manifest_path=args.manifest,
        target_service=args.target_service,
        confirmed_target_service=args.confirm_target_service,
        expected_revision=args.expected_revision,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
