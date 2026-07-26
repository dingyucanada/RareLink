from __future__ import annotations

import base64
import hashlib
import json
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from rarelink.evidence import (
    EvidencePackageError,
    EvidencePackageSource,
    build_evidence_package,
    verify_evidence_package,
)
from rarelink.security.model_signing import ModelReleaseManifest

SITES = ["hospital-a", "hospital-b", "hospital-c"]


def signing_key(tmp_path: Path) -> Path:
    path = tmp_path / "evidence-private.pem"
    path.write_bytes(
        Ed25519PrivateKey.generate().private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    os.chmod(path, 0o600)
    return path


def source(**overrides: object) -> EvidencePackageSource:
    dice = [0.7, 0.6, 0.8]
    model_release_key = Ed25519PrivateKey.generate()
    model_release_manifest = ModelReleaseManifest(
        job_id="physical-job-001",
        external_job_id="nvflare-job-001",
        contract_sha256="a" * 64,
        model_sha256="c" * 64,
        model_file_name="global-model.pt",
        approved_at="2026-07-26T00:00:00Z",
    )
    model_release_public_key = model_release_key.public_key()
    model_release_public_raw = model_release_public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    model_release_signature = base64.urlsafe_b64encode(
        model_release_key.sign(model_release_manifest.canonical_bytes())
    ).rstrip(b"=").decode()
    values: dict[str, object] = {
        "schema_version": "rarelink-evidence-source-v1",
        "study_id": "study-001",
        "job_id": "physical-job-001",
        "contract_sha256": "a" * 64,
        "bundle_sha256": "b" * 64,
        "model_sha256": "c" * 64,
        "expected_sites": SITES,
        "evidence_level": "L2",
        "generated_at": datetime(2026, 7, 26, tzinfo=UTC),
        "study_contract": {
            "schema_version": "rarelink-physical-contract-v1",
            "contract_sha256": "a" * 64,
            "quorum_required": 3,
        },
        "site_receipts": [
            {
                "site_id": site,
                "receipt_sha256": character * 64,
                "dataset_fingerprint": character * 64,
                "patient_data_exported": False,
            }
            for site, character in zip(SITES, "def", strict=True)
        ],
        "aggregate_metrics": {
            "mean_dice": sum(dice) / 3,
            "worst_site_dice": min(dice),
            "site_dice_std": 0.08164965809277264,
            "hd95": 5.0,
            "sites": [
                {"site_id": site, "dice": value, "hd95": 5.0}
                for site, value in zip(SITES, dice, strict=True)
            ],
        },
        "privacy_ledger": {
            "schema_version": "rarelink-privacy-summary-v1",
            "maximum_site_epsilon": 2.5,
            "delta": 1e-5,
        },
        "security_assessment": {
            "schema_version": "rarelink-security-assessment-v1",
            "agent_redteam_passed": True,
            "patient_data_exported": False,
        },
        "audit_chain": {
            "schema_version": "rarelink-audit-export-v1",
            "verified": True,
            "head_sha256": "9" * 64,
        },
        "model_release": {
            "schema_version": "rarelink-model-release-manifest-v1",
            "job_id": "physical-job-001",
            "contract_sha256": "a" * 64,
            "model_sha256": "c" * 64,
            "model_file_name": "global-model.pt",
            "external_job_id": "nvflare-job-001",
            "approved_at": "2026-07-26T00:00:00Z",
            "manifest_sha256": hashlib.sha256(
                model_release_manifest.canonical_bytes()
            ).hexdigest(),
            "key_fingerprint_sha256": hashlib.sha256(
                model_release_public_raw
            ).hexdigest(),
            "signature": model_release_signature,
            "algorithm": "Ed25519",
            "verified": True,
            "private_key_exported": False,
        },
        "model_release_public_key_pem": model_release_public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode(),
        "limitations": [
            "Isolated integration evidence; no three-device claim.",
            "Research use only; clinical validity is not established.",
        ],
    }
    values.update(overrides)
    return EvidencePackageSource.model_validate(values)


def build(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    package = tmp_path / "research-evidence.zip"
    receipt = build_evidence_package(
        source(),
        output_path=package,
        private_key_path=signing_key(tmp_path),
    )
    return package, receipt


def test_build_and_offline_verify_signed_evidence_package(tmp_path: Path) -> None:
    package, built = build(tmp_path)

    verified = verify_evidence_package(
        package,
        expected_key_fingerprint_sha256=str(built["key_fingerprint_sha256"]),
    )

    assert built["evidence_level"] == "L2"
    assert verified["verified"] is True
    assert verified["trust_anchor_matched"] is True
    assert verified["file_count"] == 12
    assert verified["model_release_signature_verified"] is True
    assert verified["patient_data_exported"] is False
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        assert "model-card.json" in names
        assert "data-card.json" in names
        assert "run-card.json" in names
        assert "report.md" in names
        assert not any("private" in name for name in names)


def test_evidence_package_detects_document_tampering(tmp_path: Path) -> None:
    package, built = build(tmp_path)
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(package) as source_archive, zipfile.ZipFile(tampered, "w") as target:
        for info in source_archive.infolist():
            content = source_archive.read(info.filename)
            if info.filename == "run-card.json":
                parsed = json.loads(content)
                parsed["evidence_level"] = "L3"
                content = json.dumps(parsed, separators=(",", ":")).encode()
            target.writestr(info, content)

    with pytest.raises(EvidencePackageError, match="digest"):
        verify_evidence_package(
            tampered,
            expected_key_fingerprint_sha256=str(built["key_fingerprint_sha256"]),
        )


def test_evidence_package_requires_external_signer_fingerprint(tmp_path: Path) -> None:
    package, _built = build(tmp_path)

    with pytest.raises(EvidencePackageError, match="trust policy"):
        verify_evidence_package(
            package,
            expected_key_fingerprint_sha256="0" * 64,
        )


def test_evidence_source_rejects_patient_or_local_path_fields() -> None:
    unsafe = source().model_dump()
    unsafe["security_assessment"]["patient_name"] = "not-allowed"
    with pytest.raises((EvidencePackageError, ValidationError), match="forbidden"):
        EvidencePackageSource.model_validate(unsafe)

    unsafe = source().model_dump()
    unsafe["security_assessment"]["log_location"] = "/srv/hospital/private.log"
    with pytest.raises((EvidencePackageError, ValidationError), match="local path"):
        EvidencePackageSource.model_validate(unsafe)


def test_evidence_signing_key_permissions_fail_closed(tmp_path: Path) -> None:
    key = signing_key(tmp_path)
    os.chmod(key, 0o644)

    with pytest.raises(EvidencePackageError, match="permissions"):
        build_evidence_package(
            source(),
            output_path=tmp_path / "unsafe.zip",
            private_key_path=key,
        )
