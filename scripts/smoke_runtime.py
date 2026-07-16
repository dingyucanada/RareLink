import importlib.util
import platform


def available(package: str) -> bool:
    return importlib.util.find_spec(package) is not None


print(f"architecture={platform.machine()}")
print(f"python={platform.python_version()}")
print(f"fastapi={available('fastapi')}")
print(f"torch={available('torch')}")
print(f"monai={available('monai')}")
print(f"nvflare={available('nvflare')}")

if available("torch"):
    import torch

    print(f"cuda_available={torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"gpu={torch.cuda.get_device_name(0)}")
