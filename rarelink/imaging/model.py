def segmentation_model_config() -> dict[str, object]:
    """Return the serializable model contract consumed by NVFLARE 2.7.2."""
    return {
        "class_path": "monai.networks.nets.SegResNet",
        "args": {
            "spatial_dims": 3,
            "in_channels": 4,
            "out_channels": 3,
            "init_filters": 8,
            "blocks_down": (1, 1, 1),
            "blocks_up": (1, 1),
        },
    }


def build_segmentation_model():  # type: ignore[no-untyped-def]
    """Build the small MONAI model shared by local and federated smoke jobs."""
    try:
        from monai.networks.nets import SegResNet
    except ImportError as exc:
        raise RuntimeError("MONAI is required to build the segmentation model") from exc

    config = segmentation_model_config()
    return SegResNet(**config["args"])
