"""Exercise the physical control protocol with three independent site processes.

This acceptance test does not emulate training quality and does not package any
medical data.  Each child process starts an isolated Site Agent, produces one
signed de-identified heartbeat, and exits.  The parent submits those envelopes
to a coordinator backed by a separate SQLite database and then locks a 3/3
physical-site job contract.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import queue
import tempfile
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from rarelink.api.main import app
from rarelink.config import Settings, get_settings
from rarelink.database import get_session
from rarelink.site_agent import SiteAgentSettings, create_site_agent_app
from rarelink.site_agent.schemas import CheckResult, HealthSnapshot

SITES = ("hospital-a", "hospital-b", "hospital-c")
API_TOKEN = "three-process-site-agent-token"
OPERATOR_TOKEN = "three-process-operator-token"


def _healthy_snapshot() -> HealthSnapshot:
    return HealthSnapshot(
        ready=True,
        checked_at=datetime.now(UTC),
        checks={
            "gpu": CheckResult(
                ok=True,
                status="available",
                details={"device_count": 1, "device_names_exported": False},
            ),
            "memory": CheckResult(
                ok=True,
                status="sufficient",
                details={"free_percent": 75.0},
            ),
            "disk": CheckResult(
                ok=True,
                status="sufficient",
                details={"free_percent": 80.0},
            ),
            "certificate": CheckResult(
                ok=True,
                status="valid",
                details={"certificate_subject_exported": False},
            ),
            "dataset_manifest": CheckResult(
                ok=True,
                status="present",
                details={
                    "local_path_exported": False,
                    "dataset_fingerprint": "d" * 64,
                },
            ),
            "dependencies": CheckResult(
                ok=True,
                status="available",
                details={"versions": {"monai": "verified", "nvflare": "verified"}},
            ),
        },
    )


def _site_process(
    site_id: str,
    secret: str,
    site_root: str,
    result_queue: multiprocessing.Queue,
) -> None:
    """Run in a child process and export only a signed metadata envelope."""
    root = Path(site_root)
    root.mkdir(parents=True, exist_ok=True)
    settings = SiteAgentSettings(
        _env_file=None,
        site_id=site_id,
        dataset_manifest=root / "private-manifest.json",
        artifact_root=root / "artifacts",
        startup_kit=root / "startup-kit",
        state_database=root / "site-agent.sqlite3",
        api_token=API_TOKEN,
        receipt_hmac_key=secret,
        required_modules="",
    )
    site_app = create_site_agent_app(settings, health_provider=_healthy_snapshot)
    response = TestClient(site_app).get(
        "/v1/site/heartbeat",
        headers={"Authorization": f"Bearer {API_TOKEN}"},
    )
    result_queue.put(
        {
            "site_id": site_id,
            "process_id": multiprocessing.current_process().pid,
            "status_code": response.status_code,
            "envelope": response.json(),
        }
    )


def _write_exported_job(root: Path) -> Path:
    job = root / "physical-fedavg"
    job.mkdir()
    (job / "meta.json").write_text(
        json.dumps({"name": "rarelink-three-process-acceptance"}),
        encoding="utf-8",
    )
    (job / "rarelink-job-receipt.json").write_text(
        json.dumps(
            {
                "strategy": "fedavg",
                "rounds": 5,
                "local_epochs": 1,
                "expected_sites": list(SITES),
                "local_only_manifest_required": True,
                "dataset_receipt_required": True,
                "privacy": {
                    "schema_version": "rarelink-physical-privacy-v1",
                    "enabled": False,
                    "mechanism": "none",
                    "sample_level_dp_claimed": False,
                    "end_to_end_sample_dp_claimed": False,
                },
                "update_guard": {
                    "schema_version": "rarelink-update-guard-contract-v1",
                    "transfer_type": "DIFF",
                    "max_l2_norm": 50.0,
                    "minimum_cosine_similarity": -0.25,
                    "late_round_updates_rejected": True,
                    "duplicate_site_round_updates_rejected": True,
                    "durable_replay_registry_required": True,
                    "raw_update_receipts_exported": False,
                },
                "patient_data_packaged": False,
                "certificates_packaged": False,
                "private_keys_packaged": False,
            }
        ),
        encoding="utf-8",
    )
    return job


def run_smoke(work_root: Path) -> dict[str, Any]:
    work_root.mkdir(parents=True, exist_ok=True)
    secrets = {
        site: f"three-process-hmac-key-{site}-000000000000" for site in SITES
    }
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_site_process,
            name=f"rarelink-{site}",
            args=(site, secrets[site], str(work_root / site), result_queue),
        )
        for site in SITES
    ]
    for process in processes:
        process.start()

    child_results: list[dict[str, Any]] = []
    try:
        for _ in processes:
            child_results.append(result_queue.get(timeout=30))
    except queue.Empty as exc:
        raise RuntimeError("Timed out waiting for an independent Site Agent process") from exc
    finally:
        for process in processes:
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
    if any(process.exitcode != 0 for process in processes):
        raise RuntimeError("At least one independent Site Agent process failed")
    if len({item["process_id"] for item in child_results}) != 3:
        raise RuntimeError("Acceptance requires three distinct Site Agent process IDs")

    engine = create_engine(
        f"sqlite:///{work_root / 'coordinator.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)

    def coordinator_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    coordinator_settings = Settings(
        _env_file=None,
        rarelink_allow_llm=False,
        rarelink_physical_mode="isolated-integration",
        rarelink_physical_operator_token=OPERATOR_TOKEN,
        rarelink_physical_site_secrets=json.dumps(secrets),
    )
    app.dependency_overrides[get_session] = coordinator_session
    app.dependency_overrides[get_settings] = lambda: coordinator_settings
    operator_headers = {"X-RareLink-Operator-Token": OPERATOR_TOKEN}
    try:
        with TestClient(app) as coordinator:
            for site in SITES:
                response = coordinator.post(
                    "/api/physical/sites",
                    headers=operator_headers,
                    json={
                        "site_id": site,
                        "display_name": f"{site.title()} Spark",
                        "organization": site.replace("-", "_"),
                    },
                )
                if response.status_code != 201:
                    raise RuntimeError(f"Coordinator rejected site registration: {site}")

            accepted_sites: list[str] = []
            for item in sorted(child_results, key=lambda result: result["site_id"]):
                if item["status_code"] != 200:
                    raise RuntimeError(f"Site Agent heartbeat failed: {item['site_id']}")
                envelope = item["envelope"]
                response = coordinator.post(
                    f"/api/physical/sites/{item['site_id']}/heartbeat",
                    json=envelope["payload"],
                    headers={
                        "X-RareLink-Site-Timestamp": str(envelope["timestamp"]),
                        "X-RareLink-Site-Signature": envelope["signature"],
                    },
                )
                if response.status_code != 200:
                    raise RuntimeError(
                        "Coordinator rejected signed heartbeat "
                        f"for {item['site_id']} with status {response.status_code}: "
                        f"{response.json().get('detail', 'unknown error')}"
                    )
                accepted_sites.append(response.json()["site_id"])

            job_directory = _write_exported_job(work_root)
            job_response = coordinator.post(
                "/api/physical/jobs",
                headers=operator_headers,
                json={
                    "strategy": "fedavg",
                    "expected_sites": list(SITES),
                    "total_rounds": 5,
                    "local_epochs": 1,
                    "job_directory": str(job_directory),
                },
            )
            if job_response.status_code != 201:
                raise RuntimeError("Coordinator rejected the validated 3/3 job contract")
            job = job_response.json()
            site_views = coordinator.get("/api/physical/sites").json()
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    return {
        "schema_version": "rarelink-three-process-acceptance-v1",
        "mode": "isolated-integration",
        "passed": (
            set(accepted_sites) == set(SITES)
            and all(site["status"] == "READY" for site in site_views)
            and job["status"] == "APPROVAL_PENDING"
            and job["quorum_required"] == 3
        ),
        "site_processes": [
            {
                "site_id": item["site_id"],
                "independent_process": True,
                "heartbeat_signed": True,
                "heartbeat_accepted": item["site_id"] in accepted_sites,
            }
            for item in sorted(child_results, key=lambda result: result["site_id"])
        ],
        "coordinator": {
            "registered_sites": len(site_views),
            "ready_sites": sum(site["status"] == "READY" for site in site_views),
            "job_status": job["status"],
            "quorum_required": job["quorum_required"],
            "external_job_submitted": False,
        },
        "boundaries": {
            "medical_data_used": False,
            "patient_data_exported": False,
            "real_nvflare_training_claimed": False,
            "purpose": "physical control protocol acceptance before three Spark devices arrive",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run RareLink's three-independent-process control-plane acceptance"
    )
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="rarelink-three-process-") as temporary:
        receipt = run_smoke(args.work_root or Path(temporary))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    if not receipt["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
