#!/usr/bin/env python3
"""Build a signed RareLink Research Evidence Package v2 from reviewed JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rarelink.evidence import EvidencePackageSource, build_evidence_package

MAX_SOURCE_BYTES = 8 * 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source_path = args.source.resolve()
    if args.source.is_symlink() or not source_path.is_file():
        raise SystemExit("Evidence source must be a regular non-symlink JSON file")
    raw = source_path.read_bytes()
    if len(raw) > MAX_SOURCE_BYTES:
        raise SystemExit("Evidence source exceeds the size limit")
    source = EvidencePackageSource.model_validate_json(raw)
    receipt = build_evidence_package(
        source,
        output_path=args.output,
        private_key_path=args.private_key,
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
