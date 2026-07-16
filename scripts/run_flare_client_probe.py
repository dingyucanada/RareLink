import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a bounded NVIDIA FLARE client probe")
    parser.add_argument("--client-root", type=Path, required=True)
    parser.add_argument("--site-id", default="site-c")
    parser.add_argument("--organization", default="hospital_c")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-u",
        "-m",
        "nvflare.private.fed.app.client.client_train",
        "-m",
        str(args.client_root.resolve()),
        "-s",
        "fed_client.json",
        "--set",
        "secure_train=true",
        f"uid={args.site_id}",
        f"org={args.organization}",
        "config_folder=config",
    ]
    timed_out = False
    with args.log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(
            command,
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            exit_code = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            try:
                exit_code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                exit_code = process.wait()
    result = {
        "exit_code": exit_code,
        "timed_out_after_registration_window": timed_out,
        "raw_log_included": False,
        "log_path": str(args.log.resolve()),
    }
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "log_path"}))


if __name__ == "__main__":
    main()
