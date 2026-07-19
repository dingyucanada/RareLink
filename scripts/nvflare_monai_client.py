import argparse
import copy
import json
import math
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rarelink.imaging.monai_runner import (  # noqa: E402
    SEGRESNET_SPATIAL_DIVISOR,
    _remap_label,
    _resolve_image,
)


def build_site_loaders(manifest_path: Path, site_id: str):  # type: ignore[no-untyped-def]
    from monai.data import CacheDataset, DataLoader
    from monai.transforms import (
        Compose,
        DivisiblePadd,
        EnsureChannelFirstd,
        EnsureTyped,
        Lambdad,
        LoadImaged,
        ScaleIntensityd,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset_root = manifest_path.parent
    site_cases = [case for case in manifest["cases"] if case["site_id"] == site_id]
    if len(site_cases) < 2:
        raise ValueError(f"Site {site_id!r} requires at least two cases")
    items = [
        {
            "image": _resolve_image(dataset_root, case["images"]),
            "label": str((dataset_root / case["label"]).resolve()),
        }
        for case in site_cases
    ]
    transforms = Compose(
        [
            LoadImaged(keys=["image", "label"]),
            EnsureChannelFirstd(keys=["image", "label"]),
            ScaleIntensityd(keys=["image"]),
            *(
                [
                    Lambdad(
                        keys=["label"],
                        func=lambda value: _remap_label(value, manifest["label_mapping"]),
                    )
                ]
                if manifest.get("label_mapping")
                else []
            ),
            DivisiblePadd(
                keys=["image", "label"],
                k=SEGRESNET_SPATIAL_DIVISOR,
                mode="constant",
            ),
            EnsureTyped(keys=["image", "label"]),
        ]
    )
    train_dataset = CacheDataset(items[:-1], transforms, cache_rate=1.0)
    validation_dataset = CacheDataset(items[-1:], transforms, cache_rate=1.0)
    return (
        DataLoader(train_dataset, batch_size=1, shuffle=True, num_workers=0),
        DataLoader(validation_dataset, batch_size=1, num_workers=0),
    )


def _base_model(model):  # type: ignore[no-untyped-def]
    """Return the serializable module underneath an Opacus GradSampleModule."""
    return getattr(model, "_module", model)


def _plain_tensor(value):  # type: ignore[no-untyped-def]
    """Strip MONAI MetaTensor dispatch before Opacus expanded-weights execution."""
    return value.as_tensor() if hasattr(value, "as_tensor") else value


def _prime_empty_batch_collator(data_loader) -> bool:  # type: ignore[no-untyped-def]
    """Teach Opacus the MONAI dict structure before a possible first empty draw.

    Opacus 1.6 derives first-empty fallback dtypes by iterating ``dataset[0]``.
    For a dict sample that yields string keys and therefore ``dtype=type``. A
    real non-empty collated sample avoids that upstream edge case while retaining
    the exact Poisson sampler and empty-batch semantics.
    """
    collator = getattr(data_loader, "collate_fn", None)
    if collator is None or not hasattr(collator, "first_batch"):
        return False
    if collator.first_batch is not None:
        return True
    original = getattr(collator, "wrapped_collator_fn", None)
    sample = data_loader.dataset[0]
    collator.first_batch = copy.deepcopy(original([sample]) if original else [sample])
    return True


def train_round(  # type: ignore[no-untyped-def]
    model,
    train_loader,
    device,
    epochs: int,
    fedprox_mu: float,
    optimizer,
    scaler,
):
    import torch
    from monai.losses import DiceCELoss
    from nvflare.app_opt.pt.fedproxloss import PTFedProxLoss

    reference_model = None
    if fedprox_mu > 0:
        reference_model = copy.deepcopy(model).to(device)
        reference_model.requires_grad_(False)
    loss_function = DiceCELoss(to_onehot_y=True, softmax=True)
    proximal_loss = PTFedProxLoss(mu=fedprox_mu)
    running_loss = 0.0
    scheduled_steps = 0
    nonempty_steps = 0
    model.train()
    for _epoch in range(epochs):
        for batch in train_loader:
            scheduled_steps += 1
            images = _plain_tensor(batch["image"]).to(device)
            labels = _plain_tensor(batch["label"]).to(device)
            # Poisson sampling can legitimately draw an empty batch. Expanded-
            # weights Conv3d rejects batch size zero, so an empty draw performs
            # no optimizer update while the server accountant conservatively
            # counts the scheduled mechanism invocation.
            if images.shape[0] == 0:
                continue
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, enabled=scaler.is_enabled()):
                predictions = model(images)
                loss = loss_function(predictions, labels)
                if fedprox_mu > 0:
                    loss = loss + proximal_loss(model, reference_model)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            running_loss += float(loss.detach().cpu())
            nonempty_steps += 1
    return (
        running_loss / nonempty_steps if nonempty_steps else 0.0,
        scheduled_steps,
        nonempty_steps,
    )


def evaluate(model, validation_loader, device):  # type: ignore[no-untyped-def]
    import torch
    from monai.data import decollate_batch
    from monai.inferers import sliding_window_inference
    from monai.metrics import DiceMetric, HausdorffDistanceMetric
    from monai.transforms import AsDiscrete

    metric = DiceMetric(include_background=False, reduction="mean")
    hausdorff_metric = HausdorffDistanceMetric(
        include_background=False,
        percentile=95,
        reduction="mean",
    )
    post_prediction = AsDiscrete(argmax=True, to_onehot=3)
    post_label = AsDiscrete(to_onehot=3)
    model.eval()
    with torch.inference_mode():
        for batch in validation_loader:
            images = _plain_tensor(batch["image"]).to(device)
            labels = _plain_tensor(batch["label"]).to(device)
            prediction = sliding_window_inference(images, images.shape[2:], 1, model)
            discrete_predictions = [post_prediction(item) for item in decollate_batch(prediction)]
            discrete_labels = [post_label(item) for item in decollate_batch(labels)]
            metric(y_pred=discrete_predictions, y=discrete_labels)
            hausdorff_metric(y_pred=discrete_predictions, y=discrete_labels)
    value = float(metric.aggregate().cpu())
    hd95_value = float(hausdorff_metric.aggregate().cpu())
    metric.reset()
    hausdorff_metric.reset()
    return value, hd95_value if math.isfinite(hd95_value) else None


def main() -> None:
    import nvflare.client as flare
    import torch
    from monai.utils import set_determinism

    from rarelink.imaging.model import build_segmentation_model

    parser = argparse.ArgumentParser(description="RareLink MONAI client for NVIDIA FLARE")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--fedprox-mu", type=float, default=0.0)
    parser.add_argument("--metrics-dir", type=Path)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--dp-sgd", action="store_true")
    parser.add_argument("--dp-noise-multiplier", type=float, default=1.2)
    parser.add_argument("--dp-max-grad-norm", type=float, default=1.0)
    parser.add_argument("--dp-delta", type=float, default=1e-5)
    args = parser.parse_args()

    set_determinism(args.seed)
    flare.init()
    site_id = flare.get_site_name()
    train_loader, validation_loader = build_site_loaders(args.manifest, site_id)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_segmentation_model().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-4, weight_decay=1e-5)
    scaler = torch.amp.GradScaler(
        "cuda", enabled=device.type == "cuda" and not args.dp_sgd
    )
    privacy_engine = None
    sample_count = len(train_loader.dataset)
    sample_rate = train_loader.batch_size / sample_count
    if args.dp_sgd:
        from opacus import PrivacyEngine
        from opacus.validators import ModuleValidator

        from rarelink.privacy import DPSGDConfig

        privacy_config = DPSGDConfig(
            noise_multiplier=args.dp_noise_multiplier,
            max_grad_norm=args.dp_max_grad_norm,
            delta=args.dp_delta,
        )
        privacy_config.validate()
        ModuleValidator.validate(model, strict=True)
        privacy_engine = PrivacyEngine(accountant=privacy_config.accountant, secure_mode=False)
        model, optimizer, train_loader = privacy_engine.make_private(
            module=model,
            optimizer=optimizer,
            data_loader=train_loader,
            noise_multiplier=privacy_config.noise_multiplier,
            max_grad_norm=privacy_config.max_grad_norm,
            poisson_sampling=privacy_config.poisson_sampling,
            grad_sample_mode=privacy_config.grad_sample_mode,
        )
        if not _prime_empty_batch_collator(train_loader):
            raise RuntimeError("Unable to initialize Opacus empty-batch collator")

    round_index = 0
    optimizer_steps = 0
    while flare.is_running():
        input_model = flare.receive()
        if input_model is None:
            break
        _base_model(model).load_state_dict(input_model.params)
        optimizer.state.clear()
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)
        started = time.perf_counter()
        loss, steps, nonempty_steps = train_round(
            model,
            train_loader,
            device,
            args.epochs,
            args.fedprox_mu,
            optimizer,
            scaler,
        )
        optimizer_steps += steps
        dice, hd95 = evaluate(_base_model(model), validation_loader, device)
        round_index = (
            int(input_model.current_round) + 1
            if input_model.current_round is not None
            else round_index + 1
        )
        privacy = None
        if privacy_engine:
            privacy = {
                "mechanism": "opacus_sample_level_dp_sgd",
                "accountant": "rdp",
                "epsilon": round(float(privacy_engine.get_epsilon(args.dp_delta)), 6),
                "delta": args.dp_delta,
                "noise_multiplier": args.dp_noise_multiplier,
                "max_grad_norm": args.dp_max_grad_norm,
                "sample_count": sample_count,
                "sample_rate": sample_rate,
                "optimizer_steps": optimizer_steps,
                "nonempty_optimizer_steps": nonempty_steps,
                "poisson_sampling": True,
                "grad_sample_mode": "ew",
                "secure_rng": False,
            }
        if args.metrics_dir:
            args.metrics_dir.mkdir(parents=True, exist_ok=True)
            metrics_path = args.metrics_dir / f"{site_id}-round-{round_index:03d}.json"
            metrics_path.write_text(
                json.dumps(
                    {
                        "site_id": site_id,
                        "round": round_index,
                        "mean_dice": dice,
                        "hd95": hd95,
                        "train_loss": loss,
                        "steps": steps,
                        "nonempty_steps": nonempty_steps,
                        "elapsed_seconds": round(time.perf_counter() - started, 4),
                        "peak_gpu_memory_mb": (
                            round(torch.cuda.max_memory_allocated(device) / (1024 * 1024), 3)
                            if device.type == "cuda"
                            else None
                        ),
                        "spatial_padding_multiple": SEGRESNET_SPATIAL_DIVISOR,
                        "privacy": privacy,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        cpu_parameters = {
            name: value.detach().cpu().clone()
            for name, value in _base_model(model).state_dict().items()
        }
        flare.send(
            flare.FLModel(
                params=cpu_parameters,
                metrics={
                    key: value
                    for key, value in {
                        "mean_dice": dice,
                        "hd95": hd95,
                        "train_loss": loss,
                    }.items()
                    if value is not None
                },
                meta={"NUM_STEPS_CURRENT_ROUND": steps, "site_id": site_id},
            )
        )


if __name__ == "__main__":
    main()
