#!/usr/bin/env python3
"""Collect read-only three-device field evidence without exporting credentials."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import yaml

from rarelink.deployment.field_acceptance import (
    FieldAcceptanceCredentials,
    PhysicalFieldAcceptancePlan,
    run_physical_field_acceptance,
)


def token_environment_name(site_id: str) -> str:
    return f"RARELINK_FIELD_SITE_TOKEN_{site_id.upper().replace('-', '_')}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    raw = yaml.safe_load(args.plan.read_text(encoding="utf-8"))
    plan = PhysicalFieldAcceptancePlan.model_validate(raw)
    credentials = FieldAcceptanceCredentials(
        coordinator_bearer_token=os.environ.get(
            "RARELINK_FIELD_COORDINATOR_BEARER_TOKEN",
            "",
        ),
        site_bearer_tokens={
            site.site_id: os.environ.get(token_environment_name(site.site_id), "")
            for site in plan.sites
        },
    )
    receipt = run_physical_field_acceptance(plan, credentials=credentials)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "passed": receipt["passed"],
                "achieved_evidence_level": receipt["achieved_evidence_level"],
                "receipt": str(output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
