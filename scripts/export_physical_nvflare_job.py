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
from rarelink.privacy.physical_contract import (  # noqa: E402
    build_physical_dpsgd_contract,
    disabled_physical_privacy_contract,
)


def build_privacy_contract(args: argparse.Namespace) -> dict:
    if args.strategy != "fedavg_dpsgd":
        return disabled_physical_privacy_contract()
    return build_physical_dpsgd_contract(
        noise_multiplier=args.dp_noise_multiplier,
        max_grad_norm=args.dp_max_grad_norm,
        delta=args.dp_delta,
        accountant=args.dp_accountant,
    )


def build_client_train_args(
    args: argparse.Namespace,
    privacy_contract: dict,
) -> str:
    arguments = [
        "--manifest",
        args.site_manifest_path,
        "--data-root",
        args.site_data_root_path,
        "--dataset-receipt",
        args.site_dataset_receipt_path,
        "--require-local-only-manifest",
        "--epochs",
        str(args.local_epochs),
        "--fedprox-mu",
        str(args.fedprox_mu if args.strategy == "fedprox" else 0.0),
        "--seed",
        "2026",
    ]
    if args.strategy == "fedavg_dpsgd":
        arguments.extend(
            [
                "--dp-sgd",
                "--dp-noise-multiplier",
                str(privacy_contract["noise_multiplier"]),
                "--dp-max-grad-norm",
                str(privacy_contract["max_grad_norm"]),
                "--dp-delta",
                str(privacy_contract["delta"]),
                "--dp-accountant",
                str(privacy_contract["accountant"]),
            ]
        )
    return shlex.join(arguments)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a real multi-Spark RareLink NVFLARE job")
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument(
        "--strategy",
        choices=["fedavg", "fedprox", "fedavg_dpsgd"],
        default="fedavg",
    )
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--local-epochs", type=int, default=1)
    parser.add_argument("--fedprox-mu", type=float, default=0.01)
    parser.add_argument("--dp-noise-multiplier", type=float, default=1.2)
    parser.add_argument("--dp-max-grad-norm", type=float, default=1.0)
    parser.add_argument("--dp-delta", type=float, default=1e-5)
    parser.add_argument("--dp-accountant", choices=["rdp"], default="rdp")
    parser.add_argument("--update-max-l2-norm", type=float, default=50.0)
    parser.add_argument("--update-minimum-cosine-similarity", type=float, default=-0.25)
    parser.add_argument(
        "--update-replay-db-path",
        default="/var/lib/rarelink/coordinator/update-replay.sqlite",
        help="Coordinator-local logical runtime path; registry contents are never packaged.",
    )
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
    if args.update_max_l2_norm <= 0:
        raise ValueError("update-max-l2-norm must be positive")
    if not -1 <= args.update_minimum_cosine_similarity <= 1:
        raise ValueError("update-minimum-cosine-similarity must be in [-1, 1]")
    privacy_contract = build_privacy_contract(args)

    topology = load_physical_topology(args.topology)
    try:
        from nvflare.app_opt.pt.recipes import FedAvgRecipe
        from nvflare.client.config import TransferType
        from nvflare.recipe import SimEnv
    except ImportError as exc:
        raise RuntimeError(
            "Install `rarelink[spark]` on the coordinator before exporting a job"
        ) from exc
    from rarelink.imaging.model import segmentation_model_config
    from rarelink.security.nvflare_update_filter import RareLinkUpdateGuardFilter

    train_script = Path(__file__).with_name("nvflare_monai_client.py").resolve()
    train_args = build_client_train_args(args, privacy_contract)
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
        params_transfer_type=TransferType.DIFF,
    )
    recipe.add_server_input_filter(
        RareLinkUpdateGuardFilter(
            expected_sites=[site.site_id for site in topology.sites],
            max_l2_norm=args.update_max_l2_norm,
            minimum_cosine_similarity=args.update_minimum_cosine_similarity,
            replay_db_path=args.update_replay_db_path,
        ),
        tasks=["train"],
    )
    environment = SimEnv(
        clients=[site.site_id for site in topology.sites],
        num_threads=1,
        workspace_root=str((args.output_dir.parent / ".export-workspace").resolve()),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    recipe.export(str(args.output_dir.resolve()), env=environment)
    receipt = {
        "schema_version": "rarelink-physical-job-export-v2",
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
        "privacy": privacy_contract,
        "update_guard": {
            "schema_version": "rarelink-update-guard-contract-v1",
            "transfer_type": "DIFF",
            "max_l2_norm": args.update_max_l2_norm,
            "minimum_cosine_similarity": args.update_minimum_cosine_similarity,
            "late_round_updates_rejected": True,
            "duplicate_site_round_updates_rejected": True,
            "durable_replay_registry_required": True,
            "raw_update_receipts_exported": False,
        },
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
