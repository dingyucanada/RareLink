import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rarelink.evaluation.repeated import summarize_repeated_trials  # noqa: E402
from rarelink.imaging.monai_runner import run_monai_smoke  # noqa: E402


def _aggregate_sites(site_results: list[dict[str, Any]]) -> dict[str, Any]:
    dice = [float(item["mean_foreground_dice"]) for item in site_results]
    hd95 = [float(item["hd95"]) for item in site_results if item.get("hd95") is not None]
    return {
        "mean_dice": round(statistics.fmean(dice), 6),
        "worst_site_dice": round(min(dice), 6),
        "site_dice_std": round(statistics.pstdev(dice), 6),
        "hd95": round(statistics.fmean(hd95), 6) if hd95 else None,
        "sites": [
            {
                "site_id": item["site_id"],
                "dice": item["mean_foreground_dice"],
                "hd95": item.get("hd95"),
            }
            for item in site_results
        ],
    }


def _run_local(
    manifest: Path,
    sites: list[str],
    seed: int,
    epochs: int,
    workspace: Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    site_results = [
        run_monai_smoke(
            manifest,
            site,
            workspace / "site-models",
            epochs=epochs,
            seed=seed + index,
        )
        for index, site in enumerate(sites, start=1)
    ]
    return {
        "seed": seed,
        "strategy": "local",
        "metrics": _aggregate_sites(site_results),
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "peak_gpu_memory_mb": max(
            (item["peak_gpu_memory_mb"] for item in site_results if item["peak_gpu_memory_mb"]),
            default=None,
        ),
        "workspace": str(workspace),
    }


def _run_federated(
    manifest: Path,
    strategy: str,
    seed: int,
    rounds: int,
    local_epochs: int,
    fedprox_mu: float,
    dp_epsilon: float,
    dp_fraction: float,
    dp_noise_var: float,
    dp_noise_multiplier: float,
    dp_max_grad_norm: float,
    dp_delta: float,
    workspace: Path,
) -> dict[str, Any]:
    script = Path(__file__).with_name("run_nvflare_simulation.py")
    log_path = workspace / f"{strategy}.log"
    workspace.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(script),
        "--manifest",
        str(manifest),
        "--strategy",
        strategy,
        "--seed",
        str(seed),
        "--rounds",
        str(rounds),
        "--local-epochs",
        str(local_epochs),
        "--workspace",
        str(workspace),
        "--metrics-dir",
        str(workspace / "site-metrics"),
    ]
    if strategy == "fedprox":
        command.extend(["--fedprox-mu", str(fedprox_mu)])
    if strategy == "fedavg_svt":
        command.extend(
            [
                "--dp-epsilon",
                str(dp_epsilon),
                "--dp-fraction",
                str(dp_fraction),
                "--dp-noise-var",
                str(dp_noise_var),
            ]
        )
    if strategy == "fedavg_dpsgd":
        command.extend(
            [
                "--dp-noise-multiplier",
                str(dp_noise_multiplier),
                "--dp-max-grad-norm",
                str(dp_max_grad_norm),
                "--dp-delta",
                str(dp_delta),
            ]
        )
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as log_stream:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    if completed.returncode != 0:
        details = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        raise RuntimeError(f"{strategy} seed {seed} failed: {details}")
    summary_path = workspace / f"{strategy}-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    return {
        "seed": seed,
        "strategy": strategy,
        "metrics": summary["metrics"],
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "peak_gpu_memory_mb": summary.get("peak_gpu_memory_mb"),
        "workspace": str(workspace),
        "global_model": summary.get("global_model"),
        "log_path": str(log_path),
        "privacy": summary.get("privacy"),
    }


def _summarize_privacy_comparison(
    records: list[dict[str, Any]],
    dp_epsilon: float,
    dp_fraction: float,
    dp_noise_var: float,
) -> dict[str, Any] | None:
    dpsgd = [
        item["privacy"]
        for item in records
        if item["strategy"] == "fedavg_dpsgd" and item.get("privacy")
    ]
    if dpsgd:
        epsilon_values = [float(item["epsilon"]) for item in dpsgd]
        result = dict(dpsgd[-1])
        result.update(
            {
                "repeated_trial_count": len(dpsgd),
                "epsilon_across_trials": {
                    "min": round(min(epsilon_values), 6),
                    "max": round(max(epsilon_values), 6),
                },
            }
        )
        return result
    if any(item["strategy"] == "fedavg_svt" for item in records):
        return {
            "mechanism": "nvflare_svt_model_update_filter",
            "epsilon_parameter_per_call": dp_epsilon,
            "fraction_shared": dp_fraction,
            "noise_var_parameter": dp_noise_var,
            "accounting_scope": "filter_configuration_only",
            "end_to_end_sample_dp_claimed": False,
        }
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run an aligned multi-seed Local/FedAvg/FedProx evidence matrix"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[2026, 2027, 2028])
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=["local", "fedavg", "fedprox", "fedavg_svt", "fedavg_dpsgd"],
        default=["local", "fedavg", "fedprox"],
    )
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--local-epochs", type=int, default=1)
    parser.add_argument("--fedprox-mu", type=float, default=0.01)
    parser.add_argument("--dp-epsilon", type=float, default=0.1)
    parser.add_argument("--dp-fraction", type=float, default=0.01)
    parser.add_argument("--dp-noise-var", type=float, default=0.1)
    parser.add_argument("--dp-noise-multiplier", type=float, default=1.2)
    parser.add_argument("--dp-max-grad-norm", type=float, default=1.0)
    parser.add_argument("--dp-delta", type=float, default=1e-5)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse completed seed/strategy records from the same workspace",
    )
    parser.add_argument(
        "--workspace", type=Path, default=Path("artifacts/repeated-benchmark")
    )
    args = parser.parse_args()

    manifest = args.manifest.resolve()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    sites = list(payload.get("sites", []))
    if len(sites) < 2:
        raise ValueError("Manifest must declare at least two sites")
    if len(set(args.seeds)) != len(args.seeds):
        raise ValueError("Seeds must be unique")

    args.workspace.mkdir(parents=True, exist_ok=True)
    records_path = args.workspace / "trial-records.json"
    records: list[dict[str, Any]] = (
        json.loads(records_path.read_text(encoding="utf-8"))
        if args.resume and records_path.exists()
        else []
    )
    completed_pairs = {(int(item["seed"]), str(item["strategy"])) for item in records}
    for seed in args.seeds:
        for strategy in args.strategies:
            if (seed, strategy) in completed_pairs:
                print(f"reusing seed={seed} strategy={strategy}", flush=True)
                continue
            trial_workspace = args.workspace / f"seed-{seed}" / strategy
            print(f"running seed={seed} strategy={strategy}", flush=True)
            if strategy == "local":
                record = _run_local(
                    manifest, sites, seed, args.local_epochs, trial_workspace
                )
            else:
                record = _run_federated(
                    manifest,
                    strategy,
                    seed,
                    args.rounds,
                    args.local_epochs,
                    args.fedprox_mu,
                    args.dp_epsilon,
                    args.dp_fraction,
                    args.dp_noise_var,
                    args.dp_noise_multiplier,
                    args.dp_max_grad_norm,
                    args.dp_delta,
                    trial_workspace,
                )
            records.append(record)
            records_path.write_text(
                json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    summary = summarize_repeated_trials(records)
    summary.update(
        {
            "manifest": str(manifest),
            "dataset_id": payload.get("dataset_id"),
            "sites": sites,
            "rounds": args.rounds,
            "local_epochs": args.local_epochs,
            "fedprox_mu": args.fedprox_mu,
            "privacy_comparison": _summarize_privacy_comparison(
                records,
                args.dp_epsilon,
                args.dp_fraction,
                args.dp_noise_var,
            ),
            "simulated_sites": True,
        }
    )
    summary_path = args.workspace / "repeated-summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
