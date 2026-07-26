#!/usr/bin/env python3
"""Write a deidentified secure-aggregation readiness receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rarelink.security.secure_aggregation import assess_secure_aggregation_readiness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sites",
        nargs="+",
        default=["hospital-a", "hospital-b", "hospital-c"],
    )
    parser.add_argument("--required-quorum", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    receipt = assess_secure_aggregation_readiness(
        expected_sites=tuple(args.sites),
        required_quorum=args.required_quorum,
    )
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
