import json
from pathlib import Path

from scripts.seed_competition_evidence import seed_evidence
from scripts.verify_demo_evidence import evaluate_evidence


def test_seeded_competition_evidence_verifies_without_runtime_tokens(tmp_path: Path) -> None:
    written = seed_evidence(tmp_path)
    assert len(written) == 3

    report = evaluate_evidence(tmp_path)

    assert report["passed"] is True
    assert all(report["checks"].values())
    serialized = json.dumps(report)
    assert "token" not in serialized.lower()


def test_seed_does_not_overwrite_runtime_evidence(tmp_path: Path) -> None:
    destination = tmp_path / "agent-redteam" / "summary.json"
    destination.parent.mkdir(parents=True)
    destination.write_text('{"runtime": true}', encoding="utf-8")

    seed_evidence(tmp_path)

    assert json.loads(destination.read_text(encoding="utf-8")) == {"runtime": True}
