from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DPSGDConfig:
    """Auditable sample-level DP-SGD parameters shared by every site."""

    noise_multiplier: float = 1.2
    max_grad_norm: float = 1.0
    delta: float = 1e-5
    accountant: str = "rdp"
    secure_rng: bool = False
    poisson_sampling: bool = True
    grad_sample_mode: str = "ew"

    def validate(self) -> None:
        if self.noise_multiplier <= 0:
            raise ValueError("DP-SGD noise multiplier must be positive")
        if self.max_grad_norm <= 0:
            raise ValueError("DP-SGD max gradient norm must be positive")
        if not 0 < self.delta < 1:
            raise ValueError("DP-SGD delta must be in (0, 1)")
        if self.accountant != "rdp":
            raise ValueError("RareLink currently contracts the Opacus RDP accountant")
        if self.grad_sample_mode != "ew":
            raise ValueError("RareLink's MONAI contract requires expanded-weights gradients")

    def as_public_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)


def summarize_site_privacy(
    site_metrics: list[dict[str, Any]],
    config: DPSGDConfig,
    rounds: int,
) -> dict[str, Any]:
    """Create a conservative federation-level view from cumulative site accountants."""
    config.validate()
    from opacus.accountants import RDPAccountant

    budgets = []
    for item in site_metrics:
        privacy = item.get("privacy")
        if not privacy:
            site_id = item.get("site_id", "<unknown>")
            raise ValueError(f"Site {site_id} lacks DP accounting evidence")
        reported_epsilon = float(privacy["epsilon"])
        if reported_epsilon < 0:
            raise ValueError("Accounted epsilon cannot be negative")
        per_round_steps = int(privacy["optimizer_steps"])
        total_steps = per_round_steps * rounds
        accountant = RDPAccountant()
        for _step in range(total_steps):
            accountant.step(
                noise_multiplier=config.noise_multiplier,
                sample_rate=float(privacy["sample_rate"]),
            )
        cumulative_epsilon = float(accountant.get_epsilon(delta=config.delta))
        budgets.append(
            {
                "site_id": item["site_id"],
                "epsilon": round(cumulative_epsilon, 6),
                "delta": float(privacy["delta"]),
                "sample_rate": float(privacy["sample_rate"]),
                "sample_count": int(privacy["sample_count"]),
                "optimizer_steps_per_round": per_round_steps,
                "optimizer_steps": total_steps,
                "reported_single_task_epsilon": reported_epsilon,
            }
        )
    if not budgets:
        raise ValueError("At least one site privacy budget is required")
    if any(item["delta"] != config.delta for item in budgets):
        raise ValueError("Every site must use the contracted delta")
    return {
        "mechanism": "opacus_sample_level_dp_sgd",
        "accountant": config.accountant,
        "accounting_scope": "sample_level_local_training",
        "epsilon": round(max(item["epsilon"] for item in budgets), 6),
        "delta": config.delta,
        "federation_budget_rule": "max_cumulative_site_epsilon",
        "noise_multiplier": config.noise_multiplier,
        "max_grad_norm": config.max_grad_norm,
        "poisson_sampling": config.poisson_sampling,
        "grad_sample_mode": config.grad_sample_mode,
        "secure_rng": config.secure_rng,
        "rounds_accounted": rounds,
        "site_budgets": budgets,
        "sample_level_dp_accounted": True,
        "end_to_end_sample_dp_claimed": False,
        "claim_boundary": (
            "Sample-level DP covers each site's local optimizer steps. It does not by itself "
            "provide user-level, institution-level, transport, or clinical privacy guarantees."
        ),
    }
