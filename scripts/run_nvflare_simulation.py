import argparse
import json
import shlex
import statistics
import time
from pathlib import Path


def main() -> None:
    from nvflare.app_opt.pt.recipes import FedAvgRecipe
    from nvflare.recipe import SimEnv

    from rarelink.imaging.model import segmentation_model_config

    parser = argparse.ArgumentParser(description="Run RareLink's three-site NVFLARE simulation")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--strategy", choices=["fedavg", "fedprox"], default="fedavg")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--local-epochs", type=int, default=1)
    parser.add_argument("--fedprox-mu", type=float, default=0.01)
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
        f"--fedprox-mu {proximal_mu} --metrics-dir {shlex.quote(str(metrics_dir))}"
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
        "manifest": str(manifest),
        "metrics_dir": str(metrics_dir),
        "metrics": aggregate_metrics,
        "simulated_sites": True,
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "peak_gpu_memory_mb": max(
            (item["peak_gpu_memory_mb"] for item in site_metrics if item["peak_gpu_memory_mb"]),
            default=None,
        ),
    }
    args.workspace.mkdir(parents=True, exist_ok=True)
    summary_path = args.workspace / f"{args.strategy}-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
