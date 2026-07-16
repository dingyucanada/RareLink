"""Verify the minimum, auditable evidence required by the review demo."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_evidence(root: Path) -> dict[str, Any]:
    repeated = read_json(root / "repeated-benchmark" / "repeated-summary.json")
    mtls = read_json(root / "nvflare-secure-provision" / "cross-device-mtls-evidence.json")
    redteam = read_json(root / "agent-redteam" / "summary.json")
    checks = {
        "repeated_benchmark_complete": bool(
            repeated
            and repeated.get("complete") is True
            and repeated.get("trial_count") == 25
            and len(repeated.get("seeds", [])) == 5
        ),
        "sample_level_dp_accounted": bool(
            repeated
            and repeated.get("privacy_comparison", {}).get("mechanism")
            == "opacus_sample_level_dp_sgd"
            and repeated["privacy_comparison"].get("sample_level_dp_accounted") is True
            and repeated["privacy_comparison"].get("end_to_end_sample_dp_claimed") is False
        ),
        "two_device_mtls_negative_control": bool(
            mtls
            and mtls.get("same_physical_device") is False
            and mtls.get("registration", {}).get("initial_registration_succeeded") is True
            and mtls["registration"].get("reconnect_succeeded") is True
            and mtls.get("negative_control", {}).get("wrong_identity_rejected") is True
            and mtls.get("runtime_tokens_included") is False
        ),
        "agent_redteam_complete": bool(
            redteam
            and redteam.get("all_passed") is True
            and redteam.get("case_count") == 26
            and redteam.get("passed_count") == 26
            and redteam.get("raw_attack_payloads_included") is False
        ),
    }
    return {
        "schema_version": "rarelink-demo-evidence-verification-v1",
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "artifact_root": str(root),
        "checks": checks,
        "passed": all(checks.values()),
        "claim_boundary": (
            "Checks engineering evidence artifacts only. It does not establish clinical validity, "
            "production deployment, or end-to-end privacy guarantees."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify RareLink competition demo evidence")
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    parser.add_argument(
        "--write", action="store_true", help="Persist the token-free verification receipt"
    )
    args = parser.parse_args()
    report = evaluate_evidence(args.artifact_root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.write:
        destination = args.artifact_root / "demo-evidence" / "verification.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
