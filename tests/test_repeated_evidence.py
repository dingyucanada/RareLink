import pytest

from rarelink.evaluation.repeated import summarize_repeated_trials


def record(seed: int, strategy: str, worst: float, mean: float) -> dict:
    return {
        "seed": seed,
        "strategy": strategy,
        "metrics": {
            "mean_dice": mean,
            "worst_site_dice": worst,
            "site_dice_std": 0.02,
            "hd95": 12.0,
        },
        "elapsed_seconds": 10.0,
        "peak_gpu_memory_mb": 512.0,
    }


def test_summarize_repeated_trials_reports_stability_and_local_improvement() -> None:
    records = [
        record(1, "local", 0.50, 0.60),
        record(1, "fedavg", 0.58, 0.68),
        record(1, "fedprox", 0.61, 0.69),
        record(2, "local", 0.52, 0.61),
        record(2, "fedavg", 0.59, 0.67),
        record(2, "fedprox", 0.57, 0.66),
        record(3, "local", 0.48, 0.58),
        record(3, "fedavg", 0.60, 0.69),
        record(3, "fedprox", 0.62, 0.70),
    ]

    summary = summarize_repeated_trials(records)

    assert summary["complete"] is True
    assert summary["trial_count"] == 9
    assert summary["worst_site_win_rate"]["fedprox"] == pytest.approx(2 / 3, abs=1e-6)
    improvement = summary["worst_site_improvement_vs_local"]["fedavg"]
    assert improvement["improved_seed_count"] == 3
    assert improvement["summary"]["mean"] == pytest.approx(0.09)
    assert summary["strategy_summaries"]["local"]["metrics"]["mean_dice"]["n"] == 3


def test_summarize_repeated_trials_rejects_unaligned_matrix() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        summarize_repeated_trials(
            [
                record(1, "local", 0.50, 0.60),
                record(1, "fedavg", 0.58, 0.68),
                record(2, "local", 0.52, 0.61),
            ]
        )
