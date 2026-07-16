from __future__ import annotations

import math
import statistics
from collections import Counter
from typing import Any

METRIC_NAMES = ("mean_dice", "worst_site_dice", "site_dice_std", "hd95")


def _t_critical_95(sample_count: int) -> float:
    """Two-sided 95% Student-t critical values for competition-sized runs."""
    if sample_count < 2:
        return 0.0
    values = {
        1: 12.706,
        2: 4.303,
        3: 3.182,
        4: 2.776,
        5: 2.571,
        6: 2.447,
        7: 2.365,
        8: 2.306,
        9: 2.262,
        10: 2.228,
        11: 2.201,
        12: 2.179,
        13: 2.160,
        14: 2.145,
        15: 2.131,
        16: 2.120,
        17: 2.110,
        18: 2.101,
        19: 2.093,
        20: 2.086,
        25: 2.060,
        30: 2.042,
    }
    degrees = sample_count - 1
    if degrees in values:
        return values[degrees]
    if degrees < 25:
        return values[20]
    if degrees < 30:
        return values[25]
    return 1.96


def _summary(
    values: list[float], bounds: tuple[float | None, float | None] | None = None
) -> dict[str, Any]:
    count = len(values)
    mean = statistics.fmean(values)
    standard_deviation = statistics.stdev(values) if count > 1 else 0.0
    half_width = (
        _t_critical_95(count) * standard_deviation / math.sqrt(count) if count > 1 else 0.0
    )
    lower = mean - half_width
    upper = mean + half_width
    if bounds:
        minimum, maximum = bounds
        lower = max(minimum, lower) if minimum is not None else lower
        upper = min(maximum, upper) if maximum is not None else upper
    return {
        "n": count,
        "mean": round(mean, 6),
        "std": round(standard_deviation, 6),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
        "ci95": [round(lower, 6), round(upper, 6)],
        "ci_method": "two_sided_student_t",
    }


def summarize_repeated_trials(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate aligned repeated trials and expose worst-site stability evidence."""
    if not records:
        raise ValueError("At least one trial record is required")
    strategies = sorted({str(item["strategy"]) for item in records})
    seeds = sorted({int(item["seed"]) for item in records})
    pairs = {(int(item["seed"]), str(item["strategy"])) for item in records}
    expected = {(seed, strategy) for seed in seeds for strategy in strategies}
    missing = sorted(expected - pairs)
    if missing:
        raise ValueError(f"Repeated benchmark is incomplete: missing {missing}")

    by_strategy: dict[str, Any] = {}
    for strategy in strategies:
        trials = sorted(
            (item for item in records if item["strategy"] == strategy),
            key=lambda item: int(item["seed"]),
        )
        metric_summaries = {}
        for metric_name in METRIC_NAMES:
            values = [
                float(item["metrics"][metric_name])
                for item in trials
                if item["metrics"].get(metric_name) is not None
            ]
            if metric_name in {"mean_dice", "worst_site_dice", "site_dice_std"}:
                bounds = (0.0, 1.0)
            else:
                bounds = (0.0, None)
            metric_summaries[metric_name] = _summary(values, bounds=bounds) if values else None
        elapsed = [float(item["elapsed_seconds"]) for item in trials]
        memory = [
            float(item["peak_gpu_memory_mb"])
            for item in trials
            if item.get("peak_gpu_memory_mb") is not None
        ]
        by_strategy[strategy] = {
            "trial_count": len(trials),
            "seeds": [int(item["seed"]) for item in trials],
            "metrics": metric_summaries,
            "elapsed_seconds": _summary(elapsed, bounds=(0.0, None)),
            "peak_gpu_memory_mb": _summary(memory, bounds=(0.0, None)) if memory else None,
        }

    winners: list[dict[str, Any]] = []
    winner_counts: Counter[str] = Counter()
    for seed in seeds:
        candidates = [item for item in records if int(item["seed"]) == seed]
        best_value = max(float(item["metrics"]["worst_site_dice"]) for item in candidates)
        tied = sorted(
            item["strategy"]
            for item in candidates
            if float(item["metrics"]["worst_site_dice"]) == best_value
        )
        for strategy in tied:
            winner_counts[strategy] += 1 / len(tied)
        winners.append(
            {
                "seed": seed,
                "strategies": tied,
                "worst_site_dice": round(best_value, 6),
            }
        )

    local_by_seed = {
        int(item["seed"]): float(item["metrics"]["worst_site_dice"])
        for item in records
        if item["strategy"] == "local"
    }
    improvements: dict[str, Any] = {}
    if local_by_seed:
        for strategy in strategies:
            if strategy == "local":
                continue
            values = [
                float(item["metrics"]["worst_site_dice"]) - local_by_seed[int(item["seed"])]
                for item in records
                if item["strategy"] == strategy
            ]
            improvements[strategy] = {
                "summary": _summary(values),
                "improved_seed_count": sum(value > 0 for value in values),
                "non_degraded_seed_count": sum(value >= 0 for value in values),
            }

    return {
        "schema_version": "rarelink-repeated-benchmark-v1",
        "complete": True,
        "seeds": seeds,
        "strategies": strategies,
        "trial_count": len(records),
        "strategy_summaries": by_strategy,
        "worst_site_winners": winners,
        "worst_site_win_rate": {
            strategy: round(winner_counts[strategy] / len(seeds), 6) for strategy in strategies
        },
        "worst_site_improvement_vs_local": improvements,
        "interpretation_boundary": (
            "Engineering stability evidence from simulated sites; not clinical validation."
        ),
    }
