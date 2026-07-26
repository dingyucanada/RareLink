"""Run the reproducible P0/P1 engineering acceptance gate.

The receipt records command identity, duration, exit status, and an output
digest. Raw command output remains in the local terminal and is not packaged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_check(name: str, command: list[str], *, env: dict[str, str]) -> dict[str, object]:
    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = f"{result.stdout}\n{result.stderr}".encode()
    public_command = [
        (
            "python"
            if index == 0 and value == sys.executable
            else value.replace(f"{PROJECT_ROOT}/", "")
        )
        for index, value in enumerate(command)
    ]
    receipt = {
        "name": name,
        "command": public_command,
        "exit_code": result.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "output_sha256": hashlib.sha256(combined).hexdigest(),
        "passed": result.returncode == 0,
    }
    marker = "PASS" if result.returncode == 0 else "FAIL"
    print(f"[{marker}] {name} ({receipt['duration_seconds']}s)")
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="RareLink P0/P1 automated acceptance gate")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--skip-web",
        action="store_true",
        help="Skip only when Node dependencies are unavailable in an isolated backend CI job.",
    )
    args = parser.parse_args()

    # Keep the virtual-environment launcher path. Resolving its symlink can
    # escape the venv and silently lose installed acceptance dependencies.
    python = sys.executable
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT)
    temporary_root = Path(tempfile.mkdtemp(prefix="rarelink-p0-p1-"))
    environment["RARELINK_ARTIFACT_ROOT"] = str(temporary_root / "artifacts")
    checks: list[tuple[str, list[str]]] = [
        ("backend-tests", [python, "-m", "pytest", "-q"]),
        ("python-lint", [python, "-m", "ruff", "check", "rarelink", "tests", "scripts"]),
        (
            "three-process-control-plane",
            [python, "scripts/smoke_three_site_control_plane.py"],
        ),
        (
            "fault-injection-matrix",
            [python, "scripts/run_fault_injection_matrix.py"],
        ),
        (
            "postgres-production-compose",
            [python, "scripts/validate_physical_postgres_compose.py"],
        ),
        (
            "database-migration-roundtrip",
            [python, "-m", "pytest", "-q", "tests/test_alembic_schema.py"],
        ),
    ]
    if not args.skip_web:
        checks.insert(
            2,
            ("frontend-production-build", ["npm", "--prefix", "apps/web", "run", "build"]),
        )

    started_at = datetime.now(UTC)
    receipts: list[dict[str, object]] = []
    try:
        for name, command in checks:
            if shutil.which(command[0]) is None and not Path(command[0]).exists():
                receipts.append(
                    {
                        "name": name,
                        "command": command,
                        "exit_code": 127,
                        "duration_seconds": 0.0,
                        "output_sha256": hashlib.sha256(b"executable unavailable").hexdigest(),
                        "passed": False,
                    }
                )
                print(f"[FAIL] {name}: executable unavailable")
                break
            receipt = run_check(name, command, env=environment)
            receipts.append(receipt)
            if not receipt["passed"]:
                break
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)

    passed = len(receipts) == len(checks) and all(item["passed"] for item in receipts)
    receipt = {
        "schema_version": "rarelink-p0-p1-acceptance-v1",
        "started_at_utc": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "passed": passed,
        "checks_expected": len(checks),
        "checks_completed": len(receipts),
        "checks": receipts,
        "claim_boundary": (
            "This receipt verifies local code, API, database migration, web build, and "
            "three-independent-process control-protocol behavior. It does not claim a "
            "three-physical-Spark hospital deployment, clinical validity, or regulatory approval."
        ),
        "patient_data_included": False,
        "secret_included": False,
    }
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"receipt={output}")
    print(json.dumps({"passed": passed, "checks_completed": len(receipts)}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
