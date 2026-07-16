from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from rarelink.services.policy import sanitize_llm_payload

OUTPUT_PATTERNS = {
    "diagnosis_or_treatment": re.compile(
        r"(diagnosis is|we diagnose|prescrib|should receive.{0,30}(drug|treatment)|"
        r"诊断为|确诊为|建议.{0,12}(服用|用药|治疗))",
        re.IGNORECASE,
    ),
    "patient_data_request": re.compile(
        r"((upload|send|provide).{0,30}(patient|raw MRI|DICOM)|"
        r"(上传|发送|提供).{0,20}(患者|原始影像|DICOM))",
        re.IGNORECASE,
    ),
    "clinical_overclaim": re.compile(
        r"(clinically validated|proven safe for clinical|ready for diagnosis|"
        r"可用于临床诊断|已完成临床验证)",
        re.IGNORECASE,
    ),
}


@dataclass(frozen=True)
class AgentGuardResult:
    allowed: bool
    categories: tuple[str, ...]
    blocked_paths: tuple[str, ...]
    sanitized_payload: dict[str, Any]


def _strings(value: Any):  # type: ignore[no-untyped-def]
    if isinstance(value, Mapping):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)
    elif isinstance(value, str):
        yield value


def guard_agent_input(payload: Mapping[str, Any], min_group_size: int = 5) -> AgentGuardResult:
    decision = sanitize_llm_payload(payload, min_group_size=min_group_size)
    categories = tuple(
        sorted(
            {
                "small_group" if path.split(":")[0].endswith(("sample_count", "usable_count"))
                else path.rsplit(":", 1)[-1] if ":" in path
                else "identifier_or_raw_data"
                for path in decision.blocked_fields
            }
        )
    )
    return AgentGuardResult(
        allowed=True,
        categories=categories,
        blocked_paths=tuple(decision.blocked_fields),
        sanitized_payload=decision.payload,
    )


def guard_agent_output(payload: Mapping[str, Any]) -> AgentGuardResult:
    categories: set[str] = set()
    blocked_paths: list[str] = []
    for key in ("raw_data_egress", "llm_raw_data_access"):
        if payload.get(key) is True:
            categories.add("contract_escalation")
            blocked_paths.append(key)
    for text in _strings(payload):
        for category, pattern in OUTPUT_PATTERNS.items():
            if pattern.search(text):
                categories.add(category)
    return AgentGuardResult(
        allowed=not categories,
        categories=tuple(sorted(categories)),
        blocked_paths=tuple(blocked_paths),
        sanitized_payload=dict(payload),
    )
