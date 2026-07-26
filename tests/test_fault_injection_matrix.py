from __future__ import annotations

from pathlib import Path

from rarelink.acceptance import run_fault_injection_matrix


def test_fault_injection_matrix_passes_seven_fail_closed_scenarios(
    tmp_path: Path,
) -> None:
    receipt = run_fault_injection_matrix(tmp_path / "matrix")

    assert receipt["passed"] is True
    assert receipt["scenario_count"] == 7
    assert {item["scenario_id"] for item in receipt["scenarios"]} == {
        "network-outage-reconnect",
        "agent-restart-recovery",
        "gpu-preflight-block",
        "disk-preflight-block",
        "certificate-preflight-block",
        "duplicate-update-rejected",
        "late-update-rejected",
    }
    assert all(item["passed"] for item in receipt["scenarios"])
    assert receipt["physical_devices_claimed"] is False
    assert receipt["shell_commands_executed"] is False
    rendered = str(receipt).lower()
    assert str(tmp_path).lower() not in rendered
    assert "signing-key" not in rendered
