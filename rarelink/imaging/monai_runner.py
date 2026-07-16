import json
import math
from pathlib import Path
from typing import Any


def run_monai_smoke(
    manifest_path: Path,
    site_id: str,
    output_root: Path,
    epochs: int = 1,
    seed: int = 2026,
) -> dict[str, Any]:
    """Run a tiny single-site MONAI SegResNet training job for Spark validation."""
    try:
        import torch
        from monai.data import CacheDataset, DataLoader, decollate_batch
        from monai.inferers import sliding_window_inference
        from monai.losses import DiceCELoss
        from monai.metrics import DiceMetric, HausdorffDistanceMetric
        from monai.networks.nets import SegResNet
        from monai.transforms import (
            AsDiscrete,
            Compose,
            EnsureChannelFirstd,
            EnsureTyped,
            LoadImaged,
            ScaleIntensityd,
        )
        from monai.utils import set_determinism
    except ImportError as exc:
        raise RuntimeError("Install the RareLink spark extra before running MONAI") from exc

    if epochs < 1:
        raise ValueError("epochs must be positive")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset_root = manifest_path.parent
    site_cases = [case for case in manifest["cases"] if case["site_id"] == site_id]
    if len(site_cases) < 2:
        raise ValueError(f"Site {site_id!r} needs at least two cases")

    items = [
        {
            "image": [str(dataset_root / path) for path in case["images"]],
            "label": str(dataset_root / case["label"]),
            "case_id": case["case_id"],
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
    train_items, validation_items = items[:-1], items[-1:]
    train_dataset = CacheDataset(train_items, transforms, cache_rate=1.0)
    validation_dataset = CacheDataset(validation_items, transforms, cache_rate=1.0)
    train_loader = DataLoader(train_dataset, batch_size=1, shuffle=True, num_workers=0)
    validation_loader = DataLoader(validation_dataset, batch_size=1, num_workers=0)

    set_determinism(seed=seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = SegResNet(
        spatial_dims=3,
        in_channels=4,
        out_channels=3,
        init_filters=8,
        blocks_down=(1, 1, 1),
        blocks_up=(1, 1),
    ).to(device)
    loss_function = DiceCELoss(to_onehot_y=True, softmax=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-4, weight_decay=1e-5)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    epoch_losses: list[float] = []

    for _epoch in range(epochs):
        model.train()
        running_loss = 0.0
        for batch in train_loader:
            images = batch["image"].to(device)
            labels = batch["label"].to(device)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, enabled=device.type == "cuda"):
                predictions = model(images)
                loss = loss_function(predictions, labels)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            running_loss += float(loss.detach().cpu())
        epoch_losses.append(round(running_loss / len(train_loader), 6))

    model.eval()
    metric = DiceMetric(include_background=False, reduction="mean")
    hausdorff_metric = HausdorffDistanceMetric(
        include_background=False,
        percentile=95,
        reduction="mean",
    )
    post_prediction = AsDiscrete(argmax=True, to_onehot=3)
    post_label = AsDiscrete(to_onehot=3)
    with torch.inference_mode():
        for batch in validation_loader:
            images = batch["image"].to(device)
            labels = batch["label"].to(device)
            prediction = sliding_window_inference(images, images.shape[2:], 1, model)
            discrete_predictions = [post_prediction(item) for item in decollate_batch(prediction)]
            discrete_labels = [post_label(item) for item in decollate_batch(labels)]
            metric(y_pred=discrete_predictions, y=discrete_labels)
            hausdorff_metric(y_pred=discrete_predictions, y=discrete_labels)
    dice = float(metric.aggregate().cpu())
    hd95_value = float(hausdorff_metric.aggregate().cpu())
    hd95 = round(hd95_value, 6) if math.isfinite(hd95_value) else None
    metric.reset()
    hausdorff_metric.reset()

    output_root.mkdir(parents=True, exist_ok=True)
    model_path = output_root / f"{site_id}-segresnet-smoke.pt"
    metrics_path = output_root / f"{site_id}-metrics.json"
    torch.save(model.state_dict(), model_path)
    metrics = {
        "runner": "monai-single-site-smoke",
        "site_id": site_id,
        "device": str(device),
        "epochs": epochs,
        "train_cases": len(train_items),
        "validation_cases": len(validation_items),
        "epoch_losses": epoch_losses,
        "mean_foreground_dice": round(dice, 6),
        "hd95": hd95,
        "model_path": str(model_path),
        "synthetic_data": bool(manifest.get("contains_patient_data") is False),
    }
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics
