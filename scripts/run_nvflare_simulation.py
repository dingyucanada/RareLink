import argparse
import json
import shlex
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    from nvflare.app_opt.pt.recipes import FedAvgRecipe
    from nvflare.recipe import SimEnv

    from rarelink.imaging.model import segmentation_model_config

    parser = argparse.ArgumentParser(description="Run RareLink's three-site NVFLARE simulation")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--strategy",
        choices=["fedavg", "fedprox", "fedavg_svt", "fedavg_dpsgd"],
        default="fedavg",
    )
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--local-epochs", type=int, default=1)
    parser.add_argument("--fedprox-mu", type=float, default=0.01)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--dp-epsilon", type=float, default=0.1)
    parser.add_argument("--dp-fraction", type=float, default=0.01)
    parser.add_argument("--dp-noise-var", type=float, default=0.1)
    parser.add_argument("--dp-noise-multiplier", type=float, default=1.2)
    parser.add_argument("--dp-max-grad-norm", type=float, default=1.0)
    parser.add_argument("--dp-delta", type=float, default=1e-5)
    parser.add_argument("--workspace", type=Path, default=Path("artifacts/nvflare-simulation"))
    parser.add_argument("--metrics-dir", type=Path)
    parser.add_argument("--export-dir", type=Path)
    args = parser.parse_args()

    manifest = args.manifest.resolve()
    if not manifest.exists():
        raise FileNotFoundError(manifest)
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    sites = list(manifest_payload.get("sites", []))
    if len(sites) < 2:
        raise ValueError("Manifest must declare at least two logical sites")
    metrics_dir = (args.metrics_dir or args.workspace / "site-metrics").resolve()
    proximal_mu = args.fedprox_mu if args.strategy == "fedprox" else 0.0
    client_script = Path(__file__).with_name("nvflare_monai_client.py").resolve()
    train_args = (
        f"--manifest {shlex.quote(str(manifest))} --epochs {args.local_epochs} "
        f"--fedprox-mu {proximal_mu} --metrics-dir {shlex.quote(str(metrics_dir))} "
        f"--seed {args.seed}"
    )
    if args.strategy == "fedavg_dpsgd":
        from rarelink.privacy import DPSGDConfig

        dp_config = DPSGDConfig(
            noise_multiplier=args.dp_noise_multiplier,
            max_grad_norm=args.dp_max_grad_norm,
            delta=args.dp_delta,
        )
        dp_config.validate()
        train_args += (
            f" --dp-sgd --dp-noise-multiplier {dp_config.noise_multiplier}"
            f" --dp-max-grad-norm {dp_config.max_grad_norm} --dp-delta {dp_config.delta}"
        )
    recipe = FedAvgRecipe(
        name=f"rarelink-{args.strategy}",
        min_clients=len(sites),
        num_rounds=args.rounds,
        model=segmentation_model_config(),
        train_script=str(client_script),
        train_args=train_args,
        key_metric="mean_dice",
        save_filename=f"rarelink-{args.strategy}-global.pt",
        server_memory_gc_rounds=1,
        client_memory_gc_rounds=1,
        cuda_empty_cache=True,
    )
    privacy = None
    if args.strategy == "fedavg_svt":
        from nvflare.app_common.filters.svt_privacy import SVTPrivacy

        if not 0 < args.dp_fraction <= 1:
            raise ValueError("dp-fraction must be in (0, 1]")
        if args.dp_epsilon <= 0 or args.dp_noise_var <= 0:
            raise ValueError("DP epsilon and noise variance must be positive")
        recipe.add_client_output_filter(
            SVTPrivacy(
                fraction=args.dp_fraction,
                epsilon=args.dp_epsilon,
                noise_var=args.dp_noise_var,
            ),
            tasks=["train"],
        )
        privacy = {
            "mechanism": "nvflare_svt_model_update_filter",
            "epsilon_parameter_per_call": args.dp_epsilon,
            "fraction_shared": args.dp_fraction,
            "noise_var_parameter": args.dp_noise_var,
            "calls_per_client": args.rounds,
            "accounting_scope": "filter_configuration_only",
            "end_to_end_sample_dp_claimed": False,
        }
    environment = SimEnv(
        clients=sites,
        num_threads=1,
        workspace_root=str(args.workspace.resolve()),
    )
    if args.export_dir:
        recipe.export(str(args.export_dir.resolve()), env=environment)
        print(f"exported_job={args.export_dir.resolve()}")
        return

    started = time.perf_counter()
    run = recipe.execute(environment)
    result_path = Path(run.get_result() or "")
    expected_models = list(result_path.rglob(f"rarelink-{args.strategy}-global.pt"))
    expected_models.extend(result_path.rglob("FL_global_model.pt"))
    if not expected_models:
        error_log = result_path / "server" / "log_error.txt"
        details = (
            error_log.read_text(encoding="utf-8", errors="replace") if error_log.exists() else ""
        )
        raise RuntimeError(
            "NVFLARE simulation did not produce the contracted global model. "
            f"Inspect {result_path}. Last server error: {details[-1200:]}"
        )
    site_metrics = []
    for site in sites:
        metric_files = sorted(metrics_dir.glob(f"{site}-round-*.json"))
        if not metric_files:
            continue
        payload = json.loads(metric_files[-1].read_text(encoding="utf-8"))
        site_metrics.append(
            {
                "site_id": site,
                "dice": round(float(payload["mean_dice"]), 6),
                "hd95": payload.get("hd95"),
                "round": payload["round"],
                "train_loss": round(float(payload["train_loss"]), 6),
                "elapsed_seconds": payload.get("elapsed_seconds"),
                "peak_gpu_memory_mb": payload.get("peak_gpu_memory_mb"),
                "privacy": payload.get("privacy"),
            }
        )
    dice_values = [item["dice"] for item in site_metrics]
    hd95_values = [float(item["hd95"]) for item in site_metrics if item["hd95"] is not None]
    aggregate_metrics = (
        {
            "mean_dice": round(statistics.fmean(dice_values), 6),
            "worst_site_dice": min(dice_values),
            "site_dice_std": round(statistics.pstdev(dice_values), 6),
            "hd95": round(statistics.fmean(hd95_values), 6) if hd95_values else None,
            "sites": site_metrics,
        }
        if dice_values
        else None
    )
    sdk_status = run.get_status()
    if args.strategy == "fedavg_dpsgd":
        from rarelink.privacy import summarize_site_privacy

        privacy = summarize_site_privacy(site_metrics, dp_config, args.rounds)
    summary = {
        "job_id": run.get_job_id(),
        "status": sdk_status or "completed_with_global_model",
        "sdk_status": sdk_status,
        "result": str(result_path),
        "global_model": str(expected_models[0]),
        "strategy": args.strategy,
        "sites": sites,
        "rounds": args.rounds,
        "local_epochs": args.local_epochs,
        "seed": args.seed,
        "manifest": str(manifest),
        "metrics_dir": str(metrics_dir),
        "metrics": aggregate_metrics,
        "simulated_sites": True,
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "peak_gpu_memory_mb": max(
            (item["peak_gpu_memory_mb"] for item in site_metrics if item["peak_gpu_memory_mb"]),
            default=None,
        ),
        "privacy": privacy,
    }
    args.workspace.mkdir(parents=True, exist_ok=True)
    summary_path = args.workspace / f"{args.strategy}-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
