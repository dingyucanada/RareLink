"""Verify metadata-only evidence from a live DGX Spark local-LLM run.

This verifier deliberately requires the two live receipts to exist.  It never
creates, seeds, or infers local-model evidence, so it can be used separately
from the fast competition-demo verification.
"""
# ruff: noqa: I001

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _has_live_gpu_snapshot(receipt: dict[str, Any]) -> bool:
    snapshot = receipt.get("gpu_snapshot_after")
    if not isinstance(snapshot, dict) or snapshot.get("available") is not True:
        return False
    gpus = snapshot.get("gpus")
    return bool(
        isinstance(gpus, list)
        and any(
            isinstance(gpu, dict)
            and isinstance(gpu.get("name"), str)
            and gpu.get("name")
            and isinstance(gpu.get("memory_total_mib"), int)
            and gpu["memory_total_mib"] > 0
            for gpu in gpus
        )
    )


def evaluate_local_evidence(root: Path) -> dict[str, Any]:
    """Return a token-free verdict for real, local TensorRT-LLM evidence."""
    evidence_root = root / "spark-local-inference"
    receipt = read_json(evidence_root / "last-inference.json")
    redteam = read_json(evidence_root / "redteam-summary.json")
    evidence_present = receipt is not None and redteam is not None

    checks = {
        "live_receipts_present": evidence_present,
        "local_tensorrt_backend": bool(
            receipt
            and redteam
            and receipt.get("backend") == "spark-local-tensorrt-llm"
            and redteam.get("backend") == "spark-local-tensorrt-llm"
        ),
        "no_remote_step_or_raw_patient_data": bool(
            receipt
            and redteam
            and receipt.get("remote_step_api_called") is False
            and receipt.get("raw_patient_data_transmitted") is False
            and redteam.get("remote_step_api_called") is False
        ),
        "content_not_persisted": bool(
            receipt
            and redteam
            and receipt.get("prompt_or_response_content_persisted") is False
            and redteam.get("prompts_or_model_responses_included") is False
            and redteam.get("raw_attack_payloads_included") is False
        ),
        "response_is_hashed": bool(
            receipt
            and isinstance(receipt.get("response_sha256"), str)
            and bool(SHA256_RE.fullmatch(receipt["response_sha256"]))
        ),
        "live_gpu_snapshot_captured": bool(receipt and _has_live_gpu_snapshot(receipt)),
        "local_gateway_redteam_complete": bool(
            redteam
            and redteam.get("all_passed") is True
            and redteam.get("case_count") == 26
            and redteam.get("passed_count") == 26
            and redteam.get("local_model_request_count") == 12
            and redteam.get("deterministic_output_gate_count") == 14
        ),
    }
    return {
        "schema_version": "rarelink-spark-local-inference-verification-v1",
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "artifact_root": str(root),
        "evidence_present": evidence_present,
        "checks": checks,
        "passed": evidence_present and all(checks.values()),
        "claim_boundary": (
            "Verifies metadata-only engineering receipts from a local TensorRT-LLM endpoint. "
            "It does not establish 200B throughput, clinical validity, medical-device safety, "
            "or end-to-end privacy guarantees."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify RareLink Spark-local LLM evidence")
    parser.add_argument("--artifact-root", type=Path, default=Path("artifacts"))
    parser.add_argument(
        "--write", action="store_true", help="Write a metadata-only verification receipt"
    )
    args = parser.parse_args()
    report = evaluate_local_evidence(args.artifact_root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.write:
        destination = args.artifact_root / "spark-local-inference" / "verification.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
