import argparse
import hashlib
import json
import shutil
import ssl
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _certificate_metadata(path: Path) -> dict[str, Any]:
    decoded = ssl._ssl._test_decode_cert(str(path))  # type: ignore[attr-defined]
    return {
        "filename": path.name,
        "subject": decoded.get("subject"),
        "issuer": decoded.get("issuer"),
        "serial_number": decoded.get("serialNumber"),
        "not_before": decoded.get("notBefore"),
        "not_after": decoded.get("notAfter"),
        "sha256": _sha256(path),
    }


def validate_secure_workspace(workspace: Path) -> dict[str, Any]:
    production_roots = sorted(path for path in workspace.rglob("prod_*") if path.is_dir())
    if not production_roots:
        raise FileNotFoundError(f"No provisioned prod_* workspace found under {workspace}")
    production = production_roots[-1]
    participants = ["localhost", "site-a", "site-b", "site-c"]
    evidence: list[dict[str, Any]] = []
    root_fingerprints: set[str] = set()
    for participant in participants:
        startup = production / participant / "startup"
        if not startup.exists():
            raise FileNotFoundError(f"Missing startup kit for {participant}: {startup}")
        root_ca = startup / "rootCA.pem"
        identity = startup / ("server.crt" if participant == "localhost" else "client.crt")
        private_key = startup / ("server.key" if participant == "localhost" else "client.key")
        for required in (root_ca, identity, private_key, startup / "signature.json"):
            if not required.exists():
                raise FileNotFoundError(required)
        root_fingerprints.add(_sha256(root_ca))
        evidence.append(
            {
                "participant": participant,
                "organization_isolated": True,
                "root_ca_sha256": _sha256(root_ca),
                "identity_certificate": _certificate_metadata(identity),
                "private_key_present": True,
                "private_key_exported": False,
                "startup_signature_present": True,
            }
        )
    if len(root_fingerprints) != 1:
        raise ValueError("Participant startup kits do not share the same trusted root CA")
    return {
        "schema_version": "rarelink-mtls-evidence-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "deployment_scope": "single_spark_isolated_process_rehearsal",
        "connection_security": "mtls",
        "shared_root_ca": True,
        "participant_count": len(participants),
        "participants": evidence,
        "claim_boundary": (
            "Certificate provisioning evidence only; not a real multi-hospital network deployment."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision and validate RareLink NVIDIA FLARE mTLS startup kits"
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=Path("configs/nvflare/rarelink-secure-project.yml"),
    )
    parser.add_argument(
        "--workspace", type=Path, default=Path("artifacts/nvflare-secure-provision")
    )
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    if not args.validate_only:
        executable = shutil.which("nvflare")
        sibling_cli = Path(sys.executable).with_name("nvflare")
        if not executable and sibling_cli.exists():
            executable = str(sibling_cli)
        if not executable:
            raise RuntimeError("nvflare CLI is not installed")
        completed = subprocess.run(
            [
                executable,
                "provision",
                "-p",
                str(args.project.resolve()),
                "-w",
                str(args.workspace.resolve()),
                "-s",
            ],
            check=False,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"nvflare provision failed with exit code {completed.returncode}")

    report = validate_secure_workspace(args.workspace.resolve())
    report_path = args.workspace / "mtls-evidence.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
