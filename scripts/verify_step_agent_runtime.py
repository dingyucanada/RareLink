"""Run one safe, real Step Agent request and write a metadata-only receipt.

The script is intentionally separate from the product demo: it proves that
the configured Step endpoint can return a structured RareLink protocol. The
prompt contains a fixed synthetic research question only. Neither input nor
output text is persisted; see artifacts/step-agent-inference/last-inference.json.
"""

from __future__ import annotations

import json
import time

from rarelink.config import Settings
from rarelink.services.agents import StepResearchAgentTeam


def main() -> int:
    settings = Settings()
    if not settings.rarelink_allow_llm:
        raise SystemExit("RARELINK_ALLOW_LLM is false; live Step verification is disabled")
    if not settings.step_api_key:
        raise SystemExit("STEP_API_KEY is empty; configure it in .env, never in source code")

    started = time.perf_counter()
    protocol = StepResearchAgentTeam(settings).generate_protocol(
        title="RareLink synthetic federated research workflow check",
        question=(
            "Can a fixed-budget federated engineering study report mean and worst-site "
            "segmentation metrics without using patient-level data?"
        ),
        disease_area="synthetic research workflow validation",
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    print(
        json.dumps(
            {
                "verified": protocol.source == "step-3.7",
                "source": protocol.source,
                "model": settings.step_model,
                "role": "research-director-agent",
                "latency_ms": elapsed_ms,
                "response_schema": "Protocol",
                "receipt": "artifacts/step-agent-inference/last-inference.json",
                "raw_patient_data_transmitted": False,
                "prompt_or_response_content_persisted": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
