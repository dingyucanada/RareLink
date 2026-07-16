import pytest

from rarelink.privacy import DPSGDConfig, summarize_site_privacy
from scripts.run_repeated_benchmark import _summarize_privacy_comparison


def test_dpsgd_config_rejects_invalid_budget_parameters() -> None:
    with pytest.raises(ValueError, match="noise multiplier"):
        DPSGDConfig(noise_multiplier=0).validate()
    with pytest.raises(ValueError, match="delta"):
        DPSGDConfig(delta=1).validate()


def test_federation_privacy_uses_max_cumulative_site_epsilon() -> None:
    config = DPSGDConfig(noise_multiplier=1.2, max_grad_norm=1.0, delta=1e-5)
    metrics = [
        {
            "site_id": "site-a",
            "privacy": {
                "epsilon": 3.1,
                "delta": 1e-5,
                "sample_rate": 0.25,
                "sample_count": 4,
                "optimizer_steps": 6,
            },
        },
        {
            "site_id": "site-b",
            "privacy": {
                "epsilon": 3.4,
                "delta": 1e-5,
                "sample_rate": 0.5,
                "sample_count": 2,
                "optimizer_steps": 6,
            },
        },
    ]

    summary = summarize_site_privacy(metrics, config, rounds=3)

    assert summary["epsilon"] > 3.4
    assert summary["delta"] == 1e-5
    assert summary["rounds_accounted"] == 3
    assert summary["site_budgets"][0]["optimizer_steps"] == 18
    assert summary["accounting_scope"] == "sample_level_local_training"
    assert summary["sample_level_dp_accounted"] is True
    assert summary["end_to_end_sample_dp_claimed"] is False


def test_repeated_privacy_comparison_uses_accounted_dpsgd_budget() -> None:
    records = [
        {
            "strategy": "fedavg_dpsgd",
            "privacy": {
                "mechanism": "opacus_sample_level_dp_sgd",
                "epsilon": epsilon,
                "delta": 1e-5,
            },
        }
        for epsilon in [4.2, 4.1, 4.3]
    ]

    summary = _summarize_privacy_comparison(records, 0.1, 0.01, 0.1)

    assert summary is not None
    assert summary["repeated_trial_count"] == 3
    assert summary["epsilon_across_trials"] == {"min": 4.1, "max": 4.3}
