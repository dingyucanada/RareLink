import inspect

import pytest

nvflare = pytest.importorskip("nvflare")


def test_pinned_nvflare_recipe_api_is_available() -> None:
    from nvflare.recipe import FedAvgRecipe, SimEnv

    recipe_parameters = inspect.signature(FedAvgRecipe).parameters
    environment_parameters = inspect.signature(SimEnv).parameters

    assert nvflare.__version__ == "2.7.2"
    assert {"model", "min_clients", "train_script", "num_rounds"}.issubset(recipe_parameters)
    assert {"clients", "num_threads", "workspace_root"}.issubset(environment_parameters)


def test_serializable_monai_model_contract_has_three_output_classes() -> None:
    from rarelink.imaging.model import build_segmentation_model, segmentation_model_config

    config = segmentation_model_config()
    assert config["class_path"] == "monai.networks.nets.SegResNet"
    assert config["args"]["in_channels"] == 4
    assert config["args"]["out_channels"] == 3

    model = build_segmentation_model()
    assert model.state_dict()["conv_final.2.conv.weight"].shape[0] == 3
