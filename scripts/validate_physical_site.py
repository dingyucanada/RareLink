"""Validate one hospital's Spark before it joins a RareLink FLARE study."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rarelink.deployment.topology import load_physical_topology, load_site_runtime  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_manifest_summary(manifest_path: Path, expected_site: str) -> dict[str, Any]:
    """Only emit safe aggregate manifest facts; never case IDs or file paths."""
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Local dataset manifest does not exist: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Local dataset manifest must contain a non-empty cases list")
    site_ids = {str(case.get("site_id", "")) for case in cases if isinstance(case, dict)}
    if site_ids != {expected_site}:
        raise ValueError(
            "Physical-site manifest must contain only the local site's cases; "
            f"found site IDs {sorted(site_ids)!r}, expected {expected_site!r}"
        )
    has_incomplete_case = any(
        not isinstance(case, dict) or not case.get("label") or not case.get("images")
        for case in cases
    )
    if has_incomplete_case:
        raise ValueError("Every local manifest case must declare image and label entries")
    return {
        "manifest_sha256": sha256_file(manifest_path),
        "local_case_count": len(cases),
        "site_ids_verified": [expected_site],
        "case_identifiers_exported": False,
        "image_paths_exported": False,
    }


def probe_coordinator(hostname: str, port: int, timeout: float = 4.0) -> dict[str, Any]:
    try:
        with socket.create_connection((hostname, port), timeout=timeout):
            return {"reachable": True, "hostname": hostname, "port": port}
    except OSError as exc:
        return {
            "reachable": False,
            "hostname": hostname,
            "port": port,
            "reason": type(exc).__name__,
        }


def gpu_summary() -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return {"available": False}
    completed = subprocess.run(
        [executable, "--query-gpu=name,memory.total", "--format=csv,noheader"],
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "available": completed.returncode == 0 and bool(completed.stdout.strip()),
        "device_count": len([line for line in completed.stdout.splitlines() if line.strip()]),
        "raw_device_names_exported": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Perform a safe preflight on one physical Spark site"
    )
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--site-runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/site-preflight.json"))
    parser.add_argument("--skip-network", action="store_true")
    args = parser.parse_args()

    topology = load_physical_topology(args.topology)
    runtime = load_site_runtime(args.site_runtime)
    site = next((item for item in topology.sites if item.site_id == runtime.site_id), None)
    if not site:
        raise ValueError(f"Local site {runtime.site_id!r} is absent from the approved topology")
    manifest = local_manifest_summary(runtime.dataset_manifest, runtime.site_id)
    startup_present = (runtime.startup_kit / "startup").is_dir()
    if not startup_present:
        raise FileNotFoundError(f"Provisioned startup kit is missing under {runtime.startup_kit}")
    network = (
        {"skipped": True}
        if args.skip_network
        else probe_coordinator(
            topology.coordinator.endpoint.hostname, topology.coordinator.endpoint.fed_learn_port
        )
    )
    report = {
        "schema_version": "rarelink-physical-site-preflight-v1",
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "site_id": runtime.site_id,
        "topology_federation": topology.federation_name,
        "runtime": runtime.safe_contract(),
        "local_dataset": manifest,
        "gpu": gpu_summary(),
        "nvflare_cli_available": shutil.which("nvflare") is not None,
        "coordinator_connectivity": network,
        "network_identity_verified_by_mtls": False,
        "patient_data_transferred": False,
        "environment": {"platform": sys.platform, "hostname_exported": False, "uid": os.geteuid()},
        "claim_boundary": (
            "Preflight only. A reachable TCP port is not a successful mutual-TLS registration or "
            "an authorization decision."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
