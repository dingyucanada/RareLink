import argparse
import hashlib
import json
import platform
from pathlib import Path


def _product_name() -> str:
    candidates = [
        Path("/proc/device-tree/model"),
        Path("/sys/devices/virtual/dmi/id/product_name"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8", errors="replace").strip("\x00\n ")
    return "Apple host" if platform.system() == "Darwin" else "generic host"


def main() -> None:
    parser = argparse.ArgumentParser(description="Emit a non-identifying runtime descriptor")
    parser.add_argument("--role", choices=["federation-server", "federation-client"], required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    identity_material = "|".join(
        [platform.node(), platform.system(), platform.machine(), _product_name()]
    )
    payload = {
        "role": args.role,
        "platform": f"{platform.system()} {platform.release()}",
        "architecture": platform.machine(),
        "product": _product_name(),
        "device_fingerprint": hashlib.sha256(identity_material.encode()).hexdigest(),
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
