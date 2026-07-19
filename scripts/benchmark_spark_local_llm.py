"""Measure a small, safe concurrency profile against a Spark-local LLM.

The benchmark sends fixed aggregate engineering prompts only.  It stores
latency and usage metadata, never model responses or user-supplied content.
"""
# ruff: noqa: I001

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rarelink.security.agent_guard import guard_agent_output  # noqa: E402
from rarelink.services.local_inference import gpu_runtime_snapshot  # noqa: E402

Submitter = Callable[[dict[str, Any]], tuple[str, dict[str, Any], int]]

SAFE_CONTEXT = {
    "study_scope": "synthetic federated-research engineering evidence",
    "site_count": 3,
    "raw_patient_data": False,
    "task": "state one non-clinical evidence limitation",
}


def _post_json(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=240) as response:  # nosec B310 - operator-configured local endpoint
        body = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, dict):
        raise ValueError("Local inference response must be an object")
    return body


def build_submitter(endpoint: str) -> Submitter:
    def submit(payload: dict[str, Any]) -> tuple[str, dict[str, Any], int]:
        started = time.perf_counter()
        try:
            body = _post_json(endpoint, payload)
        except HTTPError as exc:
            if exc.code not in {400, 422} or "response_format" not in payload:
                raise
            body = _post_json(
                endpoint,
                {key: value for key, value in payload.items() if key != "response_format"},
            )
        content = body["choices"][0]["message"].get("content", "")
        return content, body.get("usage", {}), round((time.perf_counter() - started) * 1000)

    return submit


def _percentile(sorted_values: list[int], percentile: float) -> int | None:
    if not sorted_values:
        return None
    index = min(len(sorted_values) - 1, round((len(sorted_values) - 1) * percentile))
    return sorted_values[index]


def _request_payload(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "temperature": 0,
        "max_tokens": 64,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return one JSON object with a short engineering limitation. Do not diagnose, "
                    "prescribe, request patient data, or claim clinical validation."
                ),
            },
            {"role": "user", "content": json.dumps(SAFE_CONTEXT, ensure_ascii=False)},
        ],
    }


def _run_level(model: str, concurrency: int, requests: int, submit: Submitter) -> dict[str, Any]:
    started = time.perf_counter()
    latencies: list[int] = []
    usage_total: dict[str, int] = {}
    accepted = 0
    rejected = 0
    transport_failures = 0

    def call_once() -> tuple[bool, int, dict[str, Any]]:
        content, usage, latency_ms = submit(_request_payload(model))
        return guard_agent_output({"content": content}).allowed, latency_ms, usage

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(call_once) for _ in range(requests)]
        for future in as_completed(futures):
            try:
                safe, latency_ms, usage = future.result()
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                transport_failures += 1
                continue
            latencies.append(latency_ms)
            if safe:
                accepted += 1
            else:
                rejected += 1
            for key, value in usage.items():
                if isinstance(value, int):
                    usage_total[key] = usage_total.get(key, 0) + value

    elapsed_seconds = max(time.perf_counter() - started, 0.001)
    ordered = sorted(latencies)
    return {
        "concurrency": concurrency,
        "request_count": requests,
        "accepted_response_count": accepted,
        "output_gate_rejection_count": rejected,
        "transport_failure_count": transport_failures,
        "all_requests_completed_safely": accepted == requests,
        "latency_ms": {
            "min": min(ordered) if ordered else None,
            "mean": round(mean(ordered), 2) if ordered else None,
            "p50": _percentile(ordered, 0.5),
            "p95": _percentile(ordered, 0.95),
            "max": max(ordered) if ordered else None,
        },
        "elapsed_seconds": round(elapsed_seconds, 3),
        "accepted_requests_per_second": round(accepted / elapsed_seconds, 4),
        "usage_total": usage_total,
    }


def run_benchmark(
    model: str,
    concurrency_levels: list[int],
    requests_per_level: int,
    submit: Submitter,
    *,
    gpu_before: dict[str, Any] | None = None,
    gpu_after: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not concurrency_levels or any(level < 1 for level in concurrency_levels):
        raise ValueError("concurrency_levels must contain positive integers")
    if requests_per_level < 1:
        raise ValueError("requests_per_level must be positive")
    levels = [
        _run_level(model, concurrency, requests_per_level, submit)
        for concurrency in sorted(set(concurrency_levels))
    ]
    successful = [level for level in levels if level["all_requests_completed_safely"]]
    peak = max(successful, key=lambda level: level["accepted_requests_per_second"], default=None)
    return {
        "schema_version": "rarelink-spark-local-llm-concurrency-benchmark-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "backend": "spark-local-tensorrt-llm",
        "model": model,
        "endpoint_scope": "loopback_or_private_spark_endpoint",
        "remote_step_api_called": False,
        "raw_patient_data_transmitted": False,
        "prompts_or_model_responses_included": False,
        "safe_fixed_workload": True,
        "levels": levels,
        "peak_safe_throughput": (
            {
                "concurrency": peak["concurrency"],
                "accepted_requests_per_second": peak["accepted_requests_per_second"],
            }
            if peak
            else None
        ),
        "gpu_snapshot_before": (
            gpu_before if gpu_before is not None else {"available": False, "gpus": []}
        ),
        "gpu_snapshot_after": (
            gpu_after if gpu_after is not None else {"available": False, "gpus": []}
        ),
        "claim_boundary": (
            "Small fixed-prompt service profile only; it is not a 200B capacity claim, a medical "
            "benchmark, or a production load test."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile safe Spark-local LLM concurrency")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8355/v1/chat/completions")
    parser.add_argument("--model", default="nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4")
    parser.add_argument("--concurrency", nargs="+", type=int, default=[1, 2, 4])
    parser.add_argument("--requests-per-level", type=int, default=4)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/spark-local-inference/concurrency-benchmark.json"),
    )
    args = parser.parse_args()
    report = run_benchmark(
        args.model,
        args.concurrency,
        args.requests_per_level,
        build_submitter(args.endpoint),
        gpu_before=gpu_runtime_snapshot(),
        gpu_after=None,
    )
    report["gpu_snapshot_after"] = gpu_runtime_snapshot()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(level["all_requests_completed_safely"] for level in report["levels"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
