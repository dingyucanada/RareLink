#!/usr/bin/env python3
"""Run RareLink's patient-free component fault matrix."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from rarelink.acceptance import run_fault_injection_matrix


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.work_root:
        receipt = run_fault_injection_matrix(args.work_root)
    else:
        with tempfile.TemporaryDirectory(prefix="rarelink-fault-matrix-") as temporary:
            receipt = run_fault_injection_matrix(Path(temporary))
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
