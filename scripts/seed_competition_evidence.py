"""Seed a local demo with an explicitly labelled, token-free evidence snapshot.

The snapshot is a compact extract of results already captured on DGX Spark. It
exists only so a reviewer can open the evidence cockpit without downloading
models, medical images, or credentials. It is never allowed to overwrite fresh
runtime evidence.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = PROJECT_ROOT / "fixtures" / "competition-evidence"

SNAPSHOTS = {
    "repeated-summary.json": Path("repeated-benchmark") / "repeated-summary.json",
    "cross-device-mtls-evidence.json": Path("nvflare-secure-provision")
    / "cross-device-mtls-evidence.json",
    "agent-redteam-summary.json": Path("agent-redteam") / "summary.json",
}


def seed_evidence(target_root: Path, overwrite: bool = False) -> list[Path]:
    written: list[Path] = []
    for source_name, relative_destination in SNAPSHOTS.items():
        source = FIXTURE_ROOT / source_name
        destination = target_root / relative_destination
        if destination.exists() and not overwrite:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        written.append(destination)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed token-free DGX Spark evidence for review demos"
    )
    parser.add_argument("--target", type=Path, default=Path("artifacts"))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    written = seed_evidence(args.target, overwrite=args.overwrite)
    if written:
        print("seeded evidence:")
        for item in written:
            print(f"- {item}")
    else:
        print("existing runtime evidence retained; nothing seeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
