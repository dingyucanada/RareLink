"""Export a portable NVFLARE job for independently deployed Spark Clients."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rarelink.deployment.topology import load_physical_topology, topology_sha256  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a real multi-Spark RareLink NVFLARE job")
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--strategy", choices=["fedavg", "fedprox"], default="fedavg")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--local-epochs", type=int, default=1)
    parser.add_argument("--fedprox-mu", type=float, default=0.01)
    parser.add_argument(
        "--site-manifest-path",
        default="/srv/rarelink/site-data/manifest.json",
        help=(
            "The same logical absolute path, supplied locally by every hospital; "
            "never a central path."
        ),
    )
    parser.add_argument(
        "--site-data-root-path",
        default="/srv/rarelink/site-data",
        help="Identical logical mount point backed by a different hospital-local volume.",
    )
    parser.add_argument(
        "--site-dataset-receipt-path",
        default="/var/lib/rarelink/site-agent/dataset-receipt.json",
        help="Hospital-local validated dataset receipt; never packaged into the job.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.rounds < 1 or args.local_epochs < 1:
        raise ValueError("rounds and local-epochs must be positive")
    if args.strategy == "fedprox" and args.fedprox_mu <= 0:
        raise ValueError("fedprox-mu must be positive for FedProx")

    topology = load_physical_topology(args.topology)
    try:
        from nvflare.app_opt.pt.recipes import FedAvgRecipe
        from nvflare.recipe import SimEnv
    except ImportError as exc:
        raise RuntimeError(
            "Install `rarelink[spark]` on the coordinator before exporting a job"
        ) from exc
    from rarelink.imaging.model import segmentation_model_config

    train_script = Path(__file__).with_name("nvflare_monai_client.py").resolve()
    train_args = " ".join(
        [
            f"--manifest {shlex.quote(args.site_manifest_path)}",
            f"--data-root {shlex.quote(args.site_data_root_path)}",
            f"--dataset-receipt {shlex.quote(args.site_dataset_receipt_path)}",
            "--require-local-only-manifest",
            f"--epochs {args.local_epochs}",
            f"--fedprox-mu {args.fedprox_mu if args.strategy == 'fedprox' else 0.0}",
            "--seed 2026",
        ]
    )
    recipe = FedAvgRecipe(
        name=f"rarelink-physical-{args.strategy}",
        min_clients=len(topology.sites),
        num_rounds=args.rounds,
        model=segmentation_model_config(),
        train_script=str(train_script),
        train_args=train_args,
        key_metric="mean_dice",
        save_filename=f"rarelink-{args.strategy}-global.pt",
        server_memory_gc_rounds=1,
        client_memory_gc_rounds=1,
        cuda_empty_cache=True,
    )
    environment = SimEnv(
        clients=[site.site_id for site in topology.sites],
        num_threads=1,
        workspace_root=str((args.output_dir.parent / ".export-workspace").resolve()),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    recipe.export(str(args.output_dir.resolve()), env=environment)
    receipt = {
        "schema_version": "rarelink-physical-job-export-v1",
        "exported_at_utc": datetime.now(UTC).isoformat(),
        "federation_name": topology.federation_name,
        "topology_sha256": topology_sha256(topology),
        "strategy": args.strategy,
        "rounds": args.rounds,
        "local_epochs": args.local_epochs,
        "expected_sites": [site.site_id for site in topology.sites],
        "site_manifest_path_contract": args.site_manifest_path,
        "site_data_root_path_contract": args.site_data_root_path,
        "site_dataset_receipt_path_contract": args.site_dataset_receipt_path,
        "local_only_manifest_required": True,
        "dataset_receipt_required": True,
        "patient_data_packaged": False,
        "certificates_packaged": False,
        "private_keys_packaged": False,
        "submission": "Use scripts/submit_physical_nvflare_job.py from the coordinator admin host.",
    }
    (args.output_dir / "rarelink-job-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
