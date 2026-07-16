import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rarelink.security.agent_guard import guard_agent_input, guard_agent_output  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RareLink's deterministic Agent red team")
    parser.add_argument("--cases", type=Path, default=Path("configs/agent-redteam-cases.json"))
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/agent-redteam/summary.json")
    )
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    results = []
    for case in cases:
        guard = (
            guard_agent_input(case["payload"])
            if case["stage"] == "input"
            else guard_agent_output(case["payload"])
        )
        observed = (
            "redacted"
            if case["stage"] == "input" and guard.blocked_paths
            else "allowed"
            if guard.allowed
            else "blocked"
        )
        category_ok = not case.get("category") or case["category"] in guard.categories
        passed = observed == case["expected"] and category_ok
        results.append(
            {
                "id": case["id"],
                "stage": case["stage"],
                "expected": case["expected"],
                "observed": observed,
                "categories": list(guard.categories),
                "passed": passed,
            }
        )
    passed_count = sum(item["passed"] for item in results)
    report = {
        "schema_version": "rarelink-agent-redteam-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "case_count": len(results),
        "passed_count": passed_count,
        "pass_rate": round(passed_count / len(results), 6),
        "all_passed": passed_count == len(results),
        "results": results,
        "raw_attack_payloads_included": False,
        "enforcement": "deterministic_pre_llm_redaction_and_post_llm_output_gate",
        "claim_boundary": "Fixed competition red-team cases; not a complete security audit.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
