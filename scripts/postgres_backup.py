#!/usr/bin/env python3
"""Create one verified RareLink PostgreSQL custom-format backup."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rarelink.database import expected_schema_revision
from rarelink.operations.postgres_backup import create_backup


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-revision", default=expected_schema_revision())
    args = parser.parse_args()
    receipt = create_backup(
        service=args.service,
        output_path=args.output,
        expected_revision=args.expected_revision,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
