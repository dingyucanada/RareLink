"""Strict, public DP-SGD contract used by physical job export and validation."""

from __future__ import annotations

import math
from typing import Any

from rarelink.privacy.dpsgd import DPSGDConfig

DP_STRATEGY = "fedavg_dpsgd"
DP_CONTRACT_KEYS = frozenset(
    {
        "schema_version",
        "enabled",
        "mechanism",
        "noise_multiplier",
        "max_grad_norm",
        "delta",
        "accountant",
        "poisson_sampling",
        "grad_sample_mode",
        "secure_rng",
        "accounting_scope",
        "epsilon_budget_mode",
        "federation_budget_rule",
        "site_epsilon_receipt_required",
        "end_to_end_sample_dp_claimed",
        "claim_boundary",
    }
)
CLAIM_BOUNDARY = (
    "Sample-level DP applies to hospital-local optimizer steps. It does not by "
    "itself provide user-level, hospital-level, transport, model-release, or "
    "clinical privacy guarantees."
)


def disabled_physical_privacy_contract() -> dict[str, Any]:
    return {
        "schema_version": "rarelink-physical-privacy-v1",
        "enabled": False,
        "mechanism": "none",
        "sample_level_dp_claimed": False,
        "end_to_end_sample_dp_claimed": False,
    }


def build_physical_dpsgd_contract(
    *,
    noise_multiplier: float,
    max_grad_norm: float,
    delta: float,
    accountant: str,
) -> dict[str, Any]:
    config = DPSGDConfig(
        noise_multiplier=noise_multiplier,
        max_grad_norm=max_grad_norm,
        delta=delta,
        accountant=accountant,
    )
    config.validate()
    if not all(
        math.isfinite(value)
        for value in (config.noise_multiplier, config.max_grad_norm, config.delta)
    ):
        raise ValueError("Physical DP-SGD parameters must be finite")
    if config.noise_multiplier > 100:
        raise ValueError("Physical DP-SGD noise multiplier exceeds the supported bound")
    if config.max_grad_norm > 1_000_000:
        raise ValueError("Physical DP-SGD gradient norm exceeds the supported bound")
    if config.delta > 0.1:
        raise ValueError("Physical DP-SGD delta exceeds the supported bound")
    return {
        "schema_version": "rarelink-physical-privacy-v1",
        "enabled": True,
        "mechanism": "opacus_sample_level_dp_sgd",
        "noise_multiplier": config.noise_multiplier,
        "max_grad_norm": config.max_grad_norm,
        "delta": config.delta,
        "accountant": config.accountant,
        "poisson_sampling": config.poisson_sampling,
        "grad_sample_mode": config.grad_sample_mode,
        "secure_rng": config.secure_rng,
        "accounting_scope": "sample_level_local_training",
        "epsilon_budget_mode": "measured_post_training_per_site",
        "federation_budget_rule": "max_cumulative_site_epsilon",
        "site_epsilon_receipt_required": True,
        "end_to_end_sample_dp_claimed": False,
        "claim_boundary": CLAIM_BOUNDARY,
    }


def validate_physical_privacy_contract(
    strategy: str,
    value: Any,
) -> dict[str, Any]:
    """Return a canonical privacy contract or reject missing/forged fields."""
    if strategy != DP_STRATEGY:
        if value is None:
            return disabled_physical_privacy_contract()
        expected = disabled_physical_privacy_contract()
        if not isinstance(value, dict) or value != expected:
            raise ValueError("Non-DP physical strategies must declare privacy disabled")
        return expected

    if not isinstance(value, dict):
        raise ValueError("fedavg_dpsgd requires a physical privacy contract")
    if set(value) != DP_CONTRACT_KEYS:
        raise ValueError("Physical DP-SGD privacy contract fields are incomplete or unknown")
    numeric_fields = ("noise_multiplier", "max_grad_norm", "delta")
    if any(
        isinstance(value[field], bool) or not isinstance(value[field], (int, float))
        for field in numeric_fields
    ):
        raise ValueError("Physical DP-SGD numeric parameters are invalid")
    canonical = build_physical_dpsgd_contract(
        noise_multiplier=float(value["noise_multiplier"]),
        max_grad_norm=float(value["max_grad_norm"]),
        delta=float(value["delta"]),
        accountant=value["accountant"] if isinstance(value["accountant"], str) else "",
    )
    if value != canonical:
        raise ValueError("Physical DP-SGD privacy contract does not match the locked boundary")
    return canonical
