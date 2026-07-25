from pathlib import Path

from scripts.smoke_three_site_control_plane import run_smoke


def test_three_independent_site_processes_complete_control_plane_acceptance(
    tmp_path: Path,
) -> None:
    receipt = run_smoke(tmp_path / "acceptance")

    assert receipt["passed"] is True
    assert receipt["mode"] == "isolated-integration"
    assert len(receipt["site_processes"]) == 3
    assert all(item["independent_process"] for item in receipt["site_processes"])
    assert all(item["heartbeat_accepted"] for item in receipt["site_processes"])
    assert receipt["coordinator"]["ready_sites"] == 3
    assert receipt["coordinator"]["quorum_required"] == 3
    assert receipt["boundaries"]["medical_data_used"] is False
