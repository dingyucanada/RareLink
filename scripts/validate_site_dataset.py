"""Validate one hospital-local NIfTI dataset and write a de-identified receipt."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rarelink.site_data import validate_site_dataset  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a local RareLink NIfTI manifest")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = validate_site_dataset(
        args.manifest,
        site_id=args.site_id,
        data_root=args.data_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
