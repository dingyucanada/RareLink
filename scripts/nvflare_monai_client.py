import argparse
import copy
import json
import math
from pathlib import Path


def build_site_loaders(manifest_path: Path, site_id: str):  # type: ignore[no-untyped-def]
    from monai.data import CacheDataset, DataLoader
    from monai.transforms import (
        Compose,
        EnsureChannelFirstd,
        EnsureTyped,
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
            "image": [str(dataset_root / path) for path in case["images"]],
            "label": str(dataset_root / case["label"]),
        }
        for case in site_cases
    ]
    transforms = Compose(
        [
            LoadImaged(keys=["image", "label"]),
            EnsureChannelFirstd(keys=["image", "label"]),
            ScaleIntensityd(keys=["image"]),
            EnsureTyped(keys=["image", "label"]),
        ]
    )
    train_dataset = CacheDataset(items[:-1], transforms, cache_rate=1.0)
    validation_dataset = CacheDataset(items[-1:], transforms, cache_rate=1.0)
    return (
        DataLoader(train_dataset, batch_size=1, shuffle=True, num_workers=0),
        DataLoader(validation_dataset, batch_size=1, num_workers=0),
    )


def train_round(model, train_loader, device, epochs: int, fedprox_mu: float):  # type: ignore[no-untyped-def]
    import torch
    from monai.losses import DiceCELoss
    from nvflare.app_opt.pt.fedproxloss import PTFedProxLoss

    reference_model = copy.deepcopy(model).to(device)
    reference_model.requires_grad_(False)
    loss_function = DiceCELoss(to_onehot_y=True, softmax=True)
    proximal_loss = PTFedProxLoss(mu=fedprox_mu)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-4, weight_decay=1e-5)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    running_loss = 0.0
    model.train()
    for _epoch in range(epochs):
        for batch in train_loader:
            images = batch["image"].to(device)
            labels = batch["label"].to(device)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, enabled=device.type == "cuda"):
                predictions = model(images)
                loss = loss_function(predictions, labels)
                if fedprox_mu > 0:
                    loss = loss + proximal_loss(model, reference_model)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            running_loss += float(loss.detach().cpu())
    steps = epochs * len(train_loader)
    return running_loss / steps, steps


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
            images = batch["image"].to(device)
            labels = batch["label"].to(device)
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
    args = parser.parse_args()

    set_determinism(args.seed)
    flare.init()
    site_id = flare.get_site_name()
    train_loader, validation_loader = build_site_loaders(args.manifest, site_id)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_segmentation_model().to(device)

    round_index = 0
    while flare.is_running():
        input_model = flare.receive()
        if input_model is None:
            break
        model.load_state_dict(input_model.params)
        loss, steps = train_round(model, train_loader, device, args.epochs, args.fedprox_mu)
        dice, hd95 = evaluate(model, validation_loader, device)
        round_index += 1
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
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        cpu_parameters = {
            name: value.detach().cpu().clone() for name, value in model.state_dict().items()
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
