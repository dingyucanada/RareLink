import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path

REGISTRATION_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} [\d:,]+).*Successfully registered client:(?P<site>[^ ]+)"
)


def capture_runtime_evidence(workspace: Path) -> dict:
    production_roots = sorted(path for path in workspace.rglob("prod_*") if path.is_dir())
    if not production_roots:
        raise FileNotFoundError(f"No prod_* workspace under {workspace}")
    production = production_roots[-1]
    server_config = json.loads(
        (production / "localhost" / "startup" / "fed_server.json").read_text(
            encoding="utf-8"
        )
    )
    server = server_config["servers"][0]
    if server.get("connection_security") != "mtls":
        raise ValueError("FLARE server is not configured for mTLS")
    server_log = (production / "localhost" / "log.txt").read_text(
        encoding="utf-8", errors="replace"
    )
    if "Server started" not in server_log:
        raise RuntimeError("FLARE server start evidence is missing")

    registrations = []
    for site in ("site-a", "site-b", "site-c"):
        client_config = json.loads(
            (production / site / "startup" / "fed_client.json").read_text(encoding="utf-8")
        )
        if client_config["client"].get("connection_security") != "mtls":
            raise ValueError(f"{site} is not configured for mTLS")
        log_path = production / site / "log.txt"
        log = log_path.read_text(encoding="utf-8", errors="replace")
        matches = [REGISTRATION_PATTERN.search(line) for line in log.splitlines()]
        match = next((item for item in reversed(matches) if item), None)
        if not match or match.group("site") != site:
            raise RuntimeError(f"Secure registration evidence missing for {site}")
        registrations.append(
            {
                "site_id": site,
                "registered": True,
                "registered_at": match.group("timestamp"),
                "connection_security": "mtls",
                "token_exported": False,
                "session_id_exported": False,
            }
        )
    return {
        "schema_version": "rarelink-mtls-runtime-evidence-v1",
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "server_started": True,
        "server_target": server["service"]["target"],
        "connection_security": "mtls",
        "registered_client_count": len(registrations),
        "registrations": registrations,
        "sensitive_runtime_tokens_included": False,
        "deployment_scope": "single_spark_isolated_process_rehearsal",
        "claim_boundary": "Secure registration rehearsal, not a real hospital network.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture token-free NVIDIA FLARE mTLS runtime evidence"
    )
    parser.add_argument(
        "--workspace", type=Path, default=Path("artifacts/nvflare-secure-provision")
    )
    args = parser.parse_args()
    report = capture_runtime_evidence(args.workspace.resolve())
    output = args.workspace / "mtls-runtime-evidence.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
