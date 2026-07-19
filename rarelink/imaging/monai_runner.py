import json
import math
import time
from pathlib import Path
from typing import Any

# The lightweight three-level SegResNet downsamples twice, so every spatial
# dimension must be divisible by four for encoder/decoder skip connections to
# align. MSD Task01 volumes are 240×240×155; padding the final axis to 156 keeps
# every observed voxel and avoids resampling public benchmark data.
SEGRESNET_SPATIAL_DIVISOR = 4


def _resolve_image(dataset_root: Path, value: str | list[str]) -> str | list[str]:
    if isinstance(value, str):
        return str((dataset_root / value).resolve())
    return [str((dataset_root / path).resolve()) for path in value]


def _remap_label(label: Any, mapping: dict[str, int]) -> Any:
    """Apply a manifest-declared label contract without cascading replacements."""
    source = label.clone() if hasattr(label, "clone") else label.copy()
    result = source.clone() if hasattr(source, "clone") else source.copy()
    for raw_value, target_value in mapping.items():
        result[source == int(raw_value)] = int(target_value)
    return result


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
            DivisiblePadd,
            EnsureChannelFirstd,
            EnsureTyped,
            Lambdad,
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
    if site_id != "centralized" and len(site_cases) < 2:
        raise ValueError(f"Site {site_id!r} needs at least two cases")

    def case_item(case: dict[str, Any]) -> dict[str, Any]:
        return {
            "image": _resolve_image(dataset_root, case["images"]),
            "label": str((dataset_root / case["label"]).resolve()),
            "case_id": case["case_id"],
        }

    if site_id == "centralized":
        train_cases: list[dict[str, Any]] = []
        validation_cases: list[dict[str, Any]] = []
        for declared_site in manifest.get("sites", []):
            cases = [case for case in manifest["cases"] if case["site_id"] == declared_site]
            if len(cases) < 2:
                raise ValueError(f"Site {declared_site!r} needs at least two cases")
            train_cases.extend(cases[:-1])
            validation_cases.append(cases[-1])
        if not validation_cases:
            raise ValueError("Manifest does not declare any sites for centralized evaluation")
    else:
        train_cases, validation_cases = site_cases[:-1], site_cases[-1:]

    items = [
        case_item(case)
        for case in [*train_cases, *validation_cases]
    ]
    label_mapping = manifest.get("label_mapping")
    transforms = Compose(
        [
            LoadImaged(keys=["image", "label"]),
            EnsureChannelFirstd(keys=["image", "label"]),
            ScaleIntensityd(keys=["image"]),
            *(
                [
                    Lambdad(
                        keys=["label"],
                        func=lambda value: _remap_label(value, label_mapping),
                    )
                ]
                if label_mapping
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
    train_items, validation_items = items[: len(train_cases)], items[len(train_cases) :]
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
        act=("RELU", {"inplace": False}),
    ).to(device)
    loss_function = DiceCELoss(to_onehot_y=True, softmax=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-4, weight_decay=1e-5)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")
    epoch_losses: list[float] = []
    started = time.perf_counter()
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)

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
        "experiment_scope": "centralized" if site_id == "centralized" else "local",
        "site_id": site_id,
        "device": str(device),
        "epochs": epochs,
        "train_cases": len(train_items),
        "validation_cases": len(validation_items),
        "epoch_losses": epoch_losses,
        "mean_foreground_dice": round(dice, 6),
        "hd95": hd95,
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "peak_gpu_memory_mb": (
            round(torch.cuda.max_memory_allocated(device) / (1024 * 1024), 3)
            if device.type == "cuda"
            else None
        ),
        "spatial_padding_multiple": SEGRESNET_SPATIAL_DIVISOR,
        "model_path": str(model_path),
        "synthetic_data": bool(manifest.get("contains_patient_data") is False),
    }
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics
