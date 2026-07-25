"""Submit a previously reviewed physical job from the coordinator admin host."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit a RareLink physical NVFLARE job")
    parser.add_argument("--admin-kit", type=Path, required=True)
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument(
        "--submit-token", required=True, help="Idempotency token, not an API secret"
    )
    parser.add_argument(
        "--receipt", type=Path, default=Path("artifacts/physical-job-submission.json")
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not (args.admin_kit / "startup").is_dir():
        raise FileNotFoundError("admin-kit must be an extracted NVFLARE admin startup kit")
    if not (args.job_dir / "meta.json").is_file():
        raise FileNotFoundError(
            "job-dir does not look like an exported NVFLARE job (meta.json missing)"
        )
    executable = shutil.which("nvflare")
    if not executable:
        raise RuntimeError("NVIDIA FLARE CLI is not installed")
    command = [
        executable,
        "job",
        "submit",
        "-j",
        str(args.job_dir.resolve()),
        "--startup-kit",
        str(args.admin_kit.resolve()),
        "--submit-token",
        args.submit_token,
    ]
    if args.dry_run:
        print(json.dumps({"dry_run": True, "command": command[:-1] + ["[redacted-token]"]}))
        return
    completed = subprocess.run(command, check=False, text=True, capture_output=True)
    receipt = {
        "schema_version": "rarelink-physical-job-submission-v1",
        "submitted_at_utc": datetime.now(UTC).isoformat(),
        "exit_code": completed.returncode,
        "job_directory": args.job_dir.name,
        "admin_kit_path_exported": False,
        "submit_token_exported": False,
        "stdout_tail": completed.stdout[-1000:],
        "stderr_tail": completed.stderr[-1000:],
        "patient_data_transferred": False,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    if completed.returncode:
        raise RuntimeError(f"nvflare job submit failed (receipt: {args.receipt})")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
