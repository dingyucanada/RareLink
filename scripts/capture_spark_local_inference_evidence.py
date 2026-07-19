"""Capture a metadata-only local-LLM receipt without persisting prompt text."""
# ruff: noqa: I001

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rarelink.services.local_inference import gpu_runtime_snapshot  # noqa: E402


SAFE_PROMPT = {
    "role": "privacy-review-agent",
    "task": (
        "Summarize aggregate engineering evidence as JSON. Do not diagnose or request patient data."
    ),
    "approved_aggregate_context": {
        "site_count": 3,
        "raw_patient_data": False,
        "sample_counts": ["<5", 12, 16],
        "engineering_scope": "synthetic competition evidence only",
    },
}


def post_json(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=240) as response:  # nosec B310 - operator-provided local endpoint
        body = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, dict):
        raise ValueError("Local inference response must be an object")
    return body


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:8355/v1/chat/completions")
    parser.add_argument(
        "--model", default="nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/spark-local-inference/last-inference.json"),
    )
    args = parser.parse_args()

    request_payload = {
        "model": args.model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Return one JSON object. Research use only."},
            {"role": "user", "content": json.dumps(SAFE_PROMPT, ensure_ascii=False)},
        ],
    }
    gpu_before = gpu_runtime_snapshot()
    started = time.perf_counter()
    try:
        response_payload = post_json(args.endpoint, request_payload)
    except HTTPError as exc:
        # Preserve compatibility with TensorRT-LLM versions without response_format support.
        if exc.code not in {400, 422}:
            raise
        compatible_payload = {
            key: value for key, value in request_payload.items() if key != "response_format"
        }
        response_payload = post_json(args.endpoint, compatible_payload)
    latency_ms = round((time.perf_counter() - started) * 1000)
    content = response_payload["choices"][0]["message"].get("content", "")
    receipt = {
        "schema_version": "rarelink-spark-local-inference-v1",
        "backend": "spark-local-tensorrt-llm",
        "model": args.model,
        "endpoint_scope": "loopback_or_private_spark_endpoint",
        "remote_step_api_called": False,
        "raw_patient_data_transmitted": False,
        "role": SAFE_PROMPT["role"],
        "latency_ms": latency_ms,
        "usage": response_payload.get("usage", {}),
        "input_policy_categories": ["small_group_suppression"],
        "response_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "prompt_or_response_content_persisted": False,
        "gpu_snapshot_before": gpu_before,
        "gpu_snapshot_after": gpu_runtime_snapshot(),
        "claim_boundary": (
            "Engineering service evidence only; this is not clinical validation "
            "or a medical-device "
            "safety claim."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
