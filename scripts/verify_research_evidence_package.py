#!/usr/bin/env python3
"""Offline verifier for one signed RareLink research evidence ZIP."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rarelink.evidence import verify_evidence_package


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--expected-key-fingerprint", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    receipt = verify_evidence_package(
        args.package,
        expected_key_fingerprint_sha256=args.expected_key_fingerprint,
    )
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
