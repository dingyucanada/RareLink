import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rarelink.security import build_cross_device_mtls_evidence  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture token-free two-device FLARE evidence")
    parser.add_argument("--server-runtime", type=Path, required=True)
    parser.add_argument("--client-runtime", type=Path, required=True)
    parser.add_argument("--initial-log", type=Path, required=True)
    parser.add_argument("--reconnect-log", type=Path, required=True)
    parser.add_argument("--rejection-log", type=Path, required=True)
    parser.add_argument("--rejection-exit-code", type=int, required=True)
    parser.add_argument("--expected-site", default="site-c")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/nvflare-secure-provision/cross-device-mtls-evidence.json"),
    )
    args = parser.parse_args()
    report = build_cross_device_mtls_evidence(
        json.loads(args.server_runtime.read_text(encoding="utf-8")),
        json.loads(args.client_runtime.read_text(encoding="utf-8")),
        args.initial_log.read_text(encoding="utf-8", errors="replace"),
        args.reconnect_log.read_text(encoding="utf-8", errors="replace"),
        args.rejection_log.read_text(encoding="utf-8", errors="replace"),
        args.expected_site,
        args.rejection_exit_code,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
