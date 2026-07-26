from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import subprocess
import sys
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
CONTRACT_SHA = "a" * 64
BUNDLE_SHA = "b" * 64
MODEL_SHA = "c" * 64
CODE_SHA = "7" * 64


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


def source_values() -> dict[str, object]:
    dice = [0.7, 0.6, 0.8]
    model_release_key = Ed25519PrivateKey.generate()
    model_release_manifest = ModelReleaseManifest(
        job_id="physical-job-001",
        external_job_id="nvflare-job-001",
        contract_sha256=CONTRACT_SHA,
        model_sha256=MODEL_SHA,
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
    return {
        "schema_version": "rarelink-evidence-source-v2",
        "study_id": "study-001",
        "job_id": "physical-job-001",
        "contract_sha256": CONTRACT_SHA,
        "bundle_sha256": BUNDLE_SHA,
        "code_sha256": CODE_SHA,
        "model_sha256": MODEL_SHA,
        "expected_sites": SITES,
        "evidence_level": "L3",
        "generated_at": datetime(2026, 7, 26, tzinfo=UTC),
        "study_contract": {
            "schema_version": "rarelink-physical-contract-v2",
            "contract_sha256": CONTRACT_SHA,
            "bundle_sha256": BUNDLE_SHA,
            "code_sha256": CODE_SHA,
            "expected_sites": SITES,
            "quorum_required": 3,
            "total_rounds": 5,
        },
        "approvals": [
            {
                "schema_version": "rarelink-approval-evidence-v1",
                "approval_type": "study-release",
                "approver_id": "pi-001",
                "approver_role": "principal-investigator",
                "approved": True,
                "contract_sha256": CONTRACT_SHA,
                "approval_receipt_sha256": "1" * 64,
                "approved_at": "2026-07-26T00:00:00Z",
            },
            {
                "schema_version": "rarelink-approval-evidence-v1",
                "approval_type": "independent-review",
                "approver_id": "reviewer-002",
                "approver_role": "independent-reviewer",
                "approved": True,
                "contract_sha256": CONTRACT_SHA,
                "approval_receipt_sha256": "2" * 64,
                "approved_at": "2026-07-26T00:05:00Z",
            },
        ],
        "site_data_cards": [
            {
                "schema_version": "rarelink-site-data-card-v1",
                "site_id": site,
                "dataset_fingerprint": character * 64,
                "manifest_sha256": number * 64,
                "data_version": f"{site}-v1",
                "case_count": 12,
                "modalities": ["T1", "T1ce", "T2", "FLAIR"],
                "quality_passed": True,
                "source_data_exported": False,
                "case_identifiers_exported": False,
                "local_paths_exported": False,
            }
            for site, character, number in zip(SITES, "def", "345", strict=True)
        ],
        "site_receipts": [
            {
                "schema_version": "rarelink-site-receipt-v2",
                "site_id": site,
                "job_id": "physical-job-001",
                "receipt_sha256": number * 64,
                "contract_sha256": CONTRACT_SHA,
                "code_sha256": CODE_SHA,
                "dataset_fingerprint": character * 64,
                "state": "COMPLETED",
                "completed_round": 5,
                "total_rounds": 5,
                "signature_verified_by_coordinator": True,
                "patient_data_exported": False,
                "private_key_exported": False,
                "local_paths_exported": False,
            }
            for site, character, number in zip(SITES, "def", "678", strict=True)
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
            "schema_version": "rarelink-privacy-ledger-v2",
            "enabled": True,
            "status": "WITHIN_BUDGET",
            "maximum_epsilon": 3.0,
            "delta": 1e-5,
            "budget_exceeded": False,
            "sites": [
                {
                    "site_id": site,
                    "epsilon": epsilon,
                    "receipt_sha256": number * 64,
                }
                for site, epsilon, number in zip(
                    SITES, [2.1, 2.2, 2.3], "abc", strict=True
                )
            ],
        },
        "security_assessment": {
            "schema_version": "rarelink-security-assessment-v2",
            "all_required_gates_passed": True,
            "gates": [
                {
                    "gate_id": gate,
                    "passed": True,
                    "receipt_sha256": character * 64,
                }
                for gate, character in zip(
                    [
                        "agent_redteam",
                        "art_membership_inference",
                        "art_model_inversion",
                        "update_guard",
                    ],
                    "1234",
                    strict=True,
                )
            ],
            "patient_data_exported": False,
        },
        "audit_chain": {
            "schema_version": "rarelink-audit-export-v2",
            "verified_by_coordinator": True,
            "truncated": False,
            "event_count": 2,
            "head_sha256": "9" * 64,
            "events": [
                {
                    "event_id": "audit-001",
                    "event_type": "JOB_APPROVED",
                    "previous_hash": "0" * 64,
                    "event_hash": "8" * 64,
                    "occurred_at": "2026-07-26T00:00:00Z",
                },
                {
                    "event_id": "audit-002",
                    "event_type": "MODEL_RELEASED",
                    "previous_hash": "8" * 64,
                    "event_hash": "9" * 64,
                    "occurred_at": "2026-07-26T01:00:00Z",
                },
            ],
        },
        "model_release": {
            "schema_version": "rarelink-model-release-manifest-v1",
            "job_id": "physical-job-001",
            "contract_sha256": CONTRACT_SHA,
            "model_sha256": MODEL_SHA,
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
            "Three-site engineering evidence; clinical validity is not established.",
            "Research use only; prospective clinical validation remains required.",
        ],
    }


def source(**overrides: object) -> EvidencePackageSource:
    values = source_values()
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


def test_build_and_offline_verify_v2_package(tmp_path: Path) -> None:
    package, built = build(tmp_path)

    verified = verify_evidence_package(
        package,
        expected_key_fingerprint_sha256=str(built["key_fingerprint_sha256"]),
    )

    assert built["evidence_level"] == "L3"
    assert built["completed_site_count"] == 3
    assert verified["verified"] is True
    assert verified["trust_anchor_matched"] is True
    assert verified["model_release_signature_verified"] is True
    assert verified["audit_chain_linkage_verified"] is True
    assert verified["privacy_budget_verified"] is True
    assert verified["security_gates_verified"] is True
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        assert {f"site-data-cards/{site}.json" for site in SITES} <= names
        assert {f"site-receipts/{site}.json" for site in SITES} <= names
        assert "approvals.json" in names
        assert "verify-evidence-package" in names
        info = archive.getinfo("verify-evidence-package")
        assert info.external_attr >> 16 & stat.S_IXUSR
        assert "site-receipts.json" not in names
        assert "data-card.json" not in names


def test_embedded_verifier_runs_without_rarelink_import(tmp_path: Path) -> None:
    package, built = build(tmp_path)
    with zipfile.ZipFile(package) as archive:
        archive.extract("verify-evidence-package", path=tmp_path)
    verifier = tmp_path / "verify-evidence-package"
    result = subprocess.run(
        [
            sys.executable,
            str(verifier),
            "--package",
            str(package),
            "--expected-key-fingerprint",
            str(built["key_fingerprint_sha256"]),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["verified"] is True


def test_package_detects_document_tampering(tmp_path: Path) -> None:
    package, built = build(tmp_path)
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(package) as source_archive, zipfile.ZipFile(tampered, "w") as target:
        for info in source_archive.infolist():
            content = source_archive.read(info.filename)
            if info.filename == "site-receipts/hospital-b.json":
                parsed = json.loads(content)
                parsed["state"] = "RUNNING"
                content = json.dumps(parsed, separators=(",", ":")).encode()
            target.writestr(info, content)

    with pytest.raises(EvidencePackageError, match="digest"):
        verify_evidence_package(
            tampered,
            expected_key_fingerprint_sha256=str(built["key_fingerprint_sha256"]),
        )


def test_package_requires_external_signer_fingerprint(tmp_path: Path) -> None:
    package, _built = build(tmp_path)
    with pytest.raises(EvidencePackageError, match="trust anchor"):
        verify_evidence_package(
            package,
            expected_key_fingerprint_sha256="0" * 64,
        )


def test_source_rejects_same_approver() -> None:
    values = source_values()
    values["approvals"][1]["approver_id"] = values["approvals"][0]["approver_id"]
    with pytest.raises(ValidationError, match="distinct approvers"):
        EvidencePackageSource.model_validate(values)


def test_source_rejects_incomplete_site() -> None:
    values = source_values()
    values["site_receipts"][1]["completed_round"] = 4
    with pytest.raises(ValidationError, match="completion failed"):
        EvidencePackageSource.model_validate(values)


def test_source_rejects_data_hash_mismatch() -> None:
    values = source_values()
    values["site_receipts"][2]["dataset_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError, match="receipt binding"):
        EvidencePackageSource.model_validate(values)


def test_source_rejects_contract_or_code_hash_mismatch() -> None:
    values = source_values()
    values["study_contract"]["code_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="study_contract"):
        EvidencePackageSource.model_validate(values)


def test_source_rejects_dp_budget_overrun() -> None:
    values = source_values()
    values["privacy_ledger"]["sites"][0]["epsilon"] = 3.1
    with pytest.raises(ValidationError, match="privacy budget"):
        EvidencePackageSource.model_validate(values)


@pytest.mark.parametrize(
    "gate_id",
    [
        "agent_redteam",
        "art_membership_inference",
        "art_model_inversion",
        "update_guard",
    ],
)
def test_source_rejects_failed_security_gate(gate_id: str) -> None:
    values = source_values()
    gate = next(
        item
        for item in values["security_assessment"]["gates"]
        if item["gate_id"] == gate_id
    )
    gate["passed"] = False
    with pytest.raises(ValidationError, match="security gate"):
        EvidencePackageSource.model_validate(values)


def test_source_rejects_broken_or_truncated_audit_chain() -> None:
    values = source_values()
    values["audit_chain"]["events"][1]["previous_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="audit chain linkage"):
        EvidencePackageSource.model_validate(values)

    values = source_values()
    values["audit_chain"]["truncated"] = True
    with pytest.raises(ValidationError, match="incomplete"):
        EvidencePackageSource.model_validate(values)


def test_source_rejects_invalid_model_release_signature() -> None:
    values = source_values()
    values["model_release"]["signature"] = "A" * 86
    with pytest.raises(ValidationError, match="signature did not verify"):
        EvidencePackageSource.model_validate(values)


def test_source_rejects_patient_fields_case_ids_keys_and_paths() -> None:
    for key, value in [
        ("patient_name", "not-allowed"),
        ("case_id", "case-001"),
        ("api_key", "not-allowed"),
        ("log_location", "/srv/hospital/private.log"),
    ]:
        unsafe = source_values()
        unsafe["security_assessment"][key] = value
        with pytest.raises(
            (EvidencePackageError, ValidationError),
            match="forbidden|local path",
        ):
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
