"""DGX Spark local LLM probing and metadata-only inference receipts.

The service deliberately never stores prompts, responses, source images, or
patient-level fields.  It records only metadata needed to demonstrate that an
approved aggregate request was served by a loopback TensorRT-LLM endpoint.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from rarelink.config import Settings


def model_list_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/models"


def probe_spark_inference(settings: Settings, timeout_seconds: float = 2.0) -> dict[str, Any]:
    """Return a safe readiness descriptor for a local OpenAI-compatible server."""
    configured = bool(settings.rarelink_spark_llm_base and settings.spark_llm_model)
    descriptor: dict[str, Any] = {
        "configured": configured,
        "available": False,
        "endpoint": settings.rarelink_spark_llm_base if configured else None,
        "model": settings.spark_llm_model if configured else None,
        "transport_scope": "Spark loopback / private deployment only",
        "data_boundary": (
            "Only policy-approved aggregate research context may enter the local model; "
            "raw images, "
            "labels, identifiers, and credentials are blocked."
        ),
        "served_models": [],
        "reason": "not_configured" if not configured else "server_not_reachable",
    }
    if not configured:
        return descriptor
    try:
        request = Request(model_list_url(settings.rarelink_spark_llm_base), method="GET")
        with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 - local configured endpoint
            payload = json.loads(response.read().decode("utf-8"))
        models = [item.get("id") for item in payload.get("data", []) if isinstance(item, dict)]
        descriptor.update(
            {
                "available": True,
                "served_models": [item for item in models if isinstance(item, str)],
                "reason": "ready",
            }
        )
        if settings.spark_llm_model not in models:
            descriptor["reason"] = "ready_model_alias_not_listed"
    except (URLError, TimeoutError, ValueError, OSError) as exc:
        descriptor["reason"] = f"unavailable:{type(exc).__name__}"
    return descriptor


def gpu_runtime_snapshot() -> dict[str, Any]:
    """Read a compact NVIDIA runtime snapshot without exposing host identity."""
    fields = "name,memory.total,memory.used,utilization.gpu,temperature.gpu"
    try:
        completed = subprocess.run(
            ["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
            check=True,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return {"available": False, "gpus": []}
    labels = [
        "name",
        "memory_total_mib",
        "memory_used_mib",
        "gpu_utilization_percent",
        "temperature_c",
    ]
    gpus = []
    for line in completed.stdout.splitlines():
        values = [item.strip() for item in line.split(",")]
        if len(values) != len(labels):
            continue
        item: dict[str, Any] = dict(zip(labels, values, strict=True))
        for numeric in labels[1:]:
            with suppress(TypeError, ValueError):
                item[numeric] = int(item[numeric])
        gpus.append(item)
    return {"available": bool(gpus), "gpus": gpus}


def write_local_inference_receipt(
    settings: Settings,
    *,
    role: str,
    model: str,
    latency_ms: int,
    usage: Any,
    policy_categories: tuple[str, ...],
    response_content: str,
    gpu_snapshot_before: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist non-sensitive proof that a local model produced a guarded result."""
    output_dir: Path = settings.artifact_root / "spark-local-inference"
    output_dir.mkdir(parents=True, exist_ok=True)
    usage_payload = usage.model_dump() if hasattr(usage, "model_dump") else (usage or {})
    receipt = {
        "schema_version": "rarelink-spark-local-inference-v1",
        "captured_at_unix": round(time.time(), 3),
        "backend": "spark-local-tensorrt-llm",
        "model": model,
        "endpoint_scope": "loopback_or_private_spark_endpoint",
        "remote_step_api_called": False,
        "raw_patient_data_transmitted": False,
        "role": role,
        "latency_ms": latency_ms,
        "usage": usage_payload,
        "input_policy_categories": list(policy_categories),
        "response_sha256": hashlib.sha256(response_content.encode("utf-8")).hexdigest(),
        "prompt_or_response_content_persisted": False,
        "gpu_snapshot_before": gpu_snapshot_before or {"available": False, "gpus": []},
        "gpu_snapshot_after": gpu_runtime_snapshot(),
        "claim_boundary": (
            "Engineering service evidence only; this is not clinical validation "
            "or a medical-device "
            "safety claim."
        ),
    }
    (output_dir / "last-inference.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return receipt


def write_step_inference_receipt(
    settings: Settings,
    *,
    role: str,
    model: str,
    latency_ms: int,
    usage: Any,
    policy_categories: tuple[str, ...],
    response_content: str,
) -> dict[str, Any]:
    """Persist metadata-only proof of a guarded Step Agent response.

    This deliberately mirrors the local inference receipt but keeps the
    transport distinction explicit. It never stores the request, response,
    API key, or aggregate values that were supplied to the model.
    """
    output_dir: Path = settings.artifact_root / "step-agent-inference"
    output_dir.mkdir(parents=True, exist_ok=True)
    usage_payload = usage.model_dump() if hasattr(usage, "model_dump") else (usage or {})
    receipt = {
        "schema_version": "rarelink-step-agent-inference-v1",
        "captured_at_unix": round(time.time(), 3),
        "backend": "step-3.7-openai-compatible",
        "model": model,
        "endpoint_scope": "configured_step_plan_api",
        "remote_step_api_called": True,
        "raw_patient_data_transmitted": False,
        "role": role,
        "latency_ms": latency_ms,
        "usage": usage_payload,
        "input_policy_categories": list(policy_categories),
        "response_sha256": hashlib.sha256(response_content.encode("utf-8")).hexdigest(),
        "prompt_or_response_content_persisted": False,
        "output_safety_gate_passed": True,
        "claim_boundary": (
            "Proof of one guarded research-workflow model call only; it is not clinical "
            "validation, a model-quality benchmark, or a guarantee of future availability."
        ),
    }
    (output_dir / "last-inference.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Keep an append-only, metadata-only role trail for the five-agent team.
    # It is safe to export as operational evidence because it has no prompt or
    # response text, aggregate values, credentials, or endpoint secret.
    with (output_dir / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(receipt, ensure_ascii=False) + "\n")
    return receipt
