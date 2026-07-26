"""Build and verify signed, offline RareLink research evidence packages."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import BaseModel, Field, field_validator, model_validator

from rarelink.evidence.standalone_verifier import (
    VerificationError as StandaloneVerificationError,
)
from rarelink.evidence.standalone_verifier import verify as standalone_verify
from rarelink.security.model_signing import ModelReleaseManifest
from rarelink.services.physical_results import parse_aggregate_metrics

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$")
DOMAIN_SEPARATOR = b"RareLink research evidence package v2\x00"
MAX_PACKAGE_BYTES = 32 * 1024 * 1024
ZERO_HASH = "0" * 64
REQUIRED_SECURITY_GATES = {
    "agent_redteam",
    "art_membership_inference",
    "art_model_inversion",
    "update_guard",
}
ROOT_PAYLOAD_FILES = {
    "study-contract.json",
    "approvals.json",
    "model-card.json",
    "run-card.json",
    "privacy-ledger.json",
    "security-assessment.json",
    "aggregate-metrics.json",
    "global-model-manifest.json",
    "audit-chain.json",
    "report.md",
    "model-release-public-key.pem",
    "verify-evidence-package",
}
FORBIDDEN_KEY_PARTS = {
    "accession",
    "address",
    "api_key",
    "authorization",
    "case_id",
    "client_secret",
    "dataset_manifest",
    "dicom_uid",
    "email",
    "file_path",
    "job_directory",
    "medical_record",
    "mrn",
    "password",
    "patient",
    "phone",
    "private_key",
    "refresh_token",
    "secret",
    "submit_token",
    "token",
}


class EvidencePackageError(ValueError):
    """Evidence was unsafe, incomplete, inconsistent, or cryptographically invalid."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_timestamp(value: datetime) -> str:
    normalized = value if value.tzinfo else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _validate_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise EvidencePackageError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _reject_sensitive(value: Any, *, trail: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key).strip().lower()
            segments = set(filter(None, re.split(r"[^a-z0-9]+", key)))
            if key in FORBIDDEN_KEY_PARTS or segments & FORBIDDEN_KEY_PARTS:
                if (
                    child is False
                    and key.endswith(("_exported", "_included", "_packaged"))
                ):
                    continue
                raise EvidencePackageError(
                    f"Evidence contains a forbidden field at {'.'.join((*trail, key))}"
                )
            _reject_sensitive(child, trail=(*trail, key))
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive(child, trail=(*trail, str(index)))
        return
    if isinstance(value, str):
        stripped = value.strip()
        if (
            stripped.startswith(("/", "~/", "\\\\"))
            or re.match(r"^[A-Za-z]:[\\/]", stripped)
            or "-----BEGIN PRIVATE KEY-----" in stripped
        ):
            raise EvidencePackageError("Evidence contains a local path or private key")


def _decode_signature(value: str) -> bytes:
    try:
        decoded = base64.urlsafe_b64decode(
            (value + "=" * (-len(value) % 4)).encode("ascii")
        )
    except (UnicodeEncodeError, ValueError) as exc:
        raise EvidencePackageError("Evidence signature encoding is invalid") from exc
    if len(decoded) != 64:
        raise EvidencePackageError("Evidence signature length is invalid")
    return decoded


def _public_fingerprint(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return _sha256_bytes(raw)


class ApprovalEvidence(BaseModel):
    """One de-identified approval attestation bound to the locked contract."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["rarelink-approval-evidence-v1"]
    approval_type: Literal["study-release", "independent-review"]
    approver_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$")
    approver_role: Literal["principal-investigator", "independent-reviewer"]
    approved: Literal[True]
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_at: datetime


class SiteDataCardEvidence(BaseModel):
    """A patient-free statement about one site's reviewed local dataset."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["rarelink-site-data-card-v1"]
    site_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$")
    dataset_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$")
    case_count: int = Field(ge=1)
    modalities: list[str] = Field(min_length=4, max_length=4)
    quality_passed: Literal[True]
    source_data_exported: Literal[False]
    case_identifiers_exported: Literal[False]
    local_paths_exported: Literal[False]

    @field_validator("modalities")
    @classmethod
    def validate_modalities(cls, values: list[str]) -> list[str]:
        if len(set(values)) != 4 or set(values) != {"T1", "T1ce", "T2", "FLAIR"}:
            raise ValueError("site data cards require T1, T1ce, T2, and FLAIR")
        return values


class SiteReceiptEvidence(BaseModel):
    """A coordinator-verified, completed site execution receipt."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["rarelink-site-receipt-v2"]
    site_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$")
    job_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$")
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["COMPLETED"]
    completed_round: int = Field(ge=1)
    total_rounds: int = Field(ge=1)
    signature_verified_by_coordinator: Literal[True]
    patient_data_exported: Literal[False]
    private_key_exported: Literal[False]
    local_paths_exported: Literal[False]


class EvidencePackageSource(BaseModel):
    """Allow-listed material for one immutable, strictly verified research release."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["rarelink-evidence-source-v2"]
    study_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$")
    job_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$")
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_sites: list[str] = Field(min_length=3, max_length=3)
    evidence_level: Literal["L3", "L4"]
    generated_at: datetime
    study_contract: dict[str, Any]
    approvals: list[ApprovalEvidence] = Field(min_length=2, max_length=2)
    site_data_cards: list[SiteDataCardEvidence] = Field(min_length=3, max_length=3)
    site_receipts: list[SiteReceiptEvidence] = Field(min_length=3, max_length=3)
    aggregate_metrics: dict[str, Any]
    privacy_ledger: dict[str, Any]
    security_assessment: dict[str, Any]
    audit_chain: dict[str, Any]
    model_release: dict[str, Any]
    model_release_public_key_pem: str = Field(min_length=100, max_length=4096)
    limitations: list[str] = Field(min_length=1, max_length=50)

    @field_validator("expected_sites")
    @classmethod
    def validate_sites(cls, sites: list[str]) -> list[str]:
        if len(set(sites)) != 3 or any(not SAFE_ID_RE.fullmatch(site) for site in sites):
            raise ValueError("expected_sites must contain three distinct safe identities")
        return sites

    @model_validator(mode="after")
    def validate_bindings_and_gates(self) -> EvidencePackageSource:
        for value in (
            self.study_contract,
            [item.model_dump(mode="json") for item in self.approvals],
            [item.model_dump(mode="json") for item in self.site_data_cards],
            [item.model_dump(mode="json") for item in self.site_receipts],
            self.aggregate_metrics,
            self.privacy_ledger,
            self.security_assessment,
            self.audit_chain,
            self.model_release,
            self.model_release_public_key_pem,
            self.limitations,
        ):
            _reject_sensitive(value)
        if any(not item.strip() or len(item) > 500 for item in self.limitations):
            raise ValueError("limitations must be non-empty strings up to 500 characters")
        self._validate_contract_and_approvals()
        self._validate_sites_and_completion()
        parse_aggregate_metrics(
            self.aggregate_metrics,
            (self.expected_sites[0], self.expected_sites[1], self.expected_sites[2]),
        )
        self._validate_privacy_ledger()
        self._validate_security_assessment()
        self._validate_audit_chain()
        self._validate_model_release()
        return self

    def _validate_contract_and_approvals(self) -> None:
        if (
            self.study_contract.get("contract_sha256") != self.contract_sha256
            or self.study_contract.get("bundle_sha256") != self.bundle_sha256
            or self.study_contract.get("code_sha256") != self.code_sha256
            or self.study_contract.get("expected_sites") != self.expected_sites
            or self.study_contract.get("quorum_required") != 3
            or not isinstance(self.study_contract.get("total_rounds"), int)
            or self.study_contract["total_rounds"] < 1
        ):
            raise ValueError("study_contract does not bind contract, code, sites, and rounds")
        if (
            {item.approval_type for item in self.approvals}
            != {"study-release", "independent-review"}
            or len({item.approver_id for item in self.approvals}) != 2
            or any(
                item.contract_sha256 != self.contract_sha256
                for item in self.approvals
            )
        ):
            raise ValueError("two distinct approvers must approve the same contract")
        expected_roles = {
            "study-release": "principal-investigator",
            "independent-review": "independent-reviewer",
        }
        if any(
            item.approver_role != expected_roles[item.approval_type]
            for item in self.approvals
        ):
            raise ValueError("approval roles do not match the required separation")

    def _validate_sites_and_completion(self) -> None:
        cards = {item.site_id: item for item in self.site_data_cards}
        receipts = {item.site_id: item for item in self.site_receipts}
        if (
            len(cards) != 3
            or len(receipts) != 3
            or set(cards) != set(self.expected_sites)
            or set(receipts) != set(self.expected_sites)
        ):
            raise ValueError("data cards and receipts must cover all three sites once")
        total_rounds = self.study_contract["total_rounds"]
        for site in self.expected_sites:
            receipt = receipts[site]
            if (
                receipt.job_id != self.job_id
                or receipt.contract_sha256 != self.contract_sha256
                or receipt.code_sha256 != self.code_sha256
                or receipt.dataset_fingerprint != cards[site].dataset_fingerprint
                or receipt.completed_round != total_rounds
                or receipt.total_rounds != total_rounds
            ):
                raise ValueError(f"site receipt binding or completion failed for {site}")

    def _validate_privacy_ledger(self) -> None:
        ledger = self.privacy_ledger
        if (
            ledger.get("budget_exceeded") is not False
            or ledger.get("status") not in {"WITHIN_BUDGET", "NOT_APPLICABLE"}
            or not isinstance(ledger.get("enabled"), bool)
        ):
            raise ValueError("privacy ledger does not pass the budget gate")
        if ledger["enabled"]:
            maximum = ledger.get("maximum_epsilon")
            delta = ledger.get("delta")
            sites = ledger.get("sites")
            if (
                isinstance(maximum, bool)
                or not isinstance(maximum, int | float)
                or maximum <= 0
                or isinstance(delta, bool)
                or not isinstance(delta, int | float)
                or not 0 < delta < 1
                or not isinstance(sites, list)
                or len(sites) != 3
            ):
                raise ValueError("privacy ledger accounting is incomplete")
            seen: set[str] = set()
            for item in sites:
                if not isinstance(item, dict):
                    raise ValueError("site privacy accounting is invalid")
                site = item.get("site_id")
                epsilon = item.get("epsilon")
                _validate_digest(item.get("receipt_sha256"), "privacy receipt")
                if (
                    site not in self.expected_sites
                    or site in seen
                    or isinstance(epsilon, bool)
                    or not isinstance(epsilon, int | float)
                    or epsilon < 0
                    or epsilon > maximum
                ):
                    raise ValueError("site privacy budget is invalid or exceeded")
                seen.add(str(site))
            if seen != set(self.expected_sites) or ledger["status"] != "WITHIN_BUDGET":
                raise ValueError("privacy ledger does not cover all expected sites")
        elif ledger["status"] != "NOT_APPLICABLE":
            raise ValueError("disabled DP accounting must be marked NOT_APPLICABLE")

    def _validate_security_assessment(self) -> None:
        assessment = self.security_assessment
        gates = assessment.get("gates")
        if (
            assessment.get("all_required_gates_passed") is not True
            or not isinstance(gates, list)
            or len(gates) != len(REQUIRED_SECURITY_GATES)
        ):
            raise ValueError("security assessment does not pass every required gate")
        seen: set[str] = set()
        for gate in gates:
            if not isinstance(gate, dict):
                raise ValueError("security gate evidence is invalid")
            gate_id = gate.get("gate_id")
            if (
                gate_id not in REQUIRED_SECURITY_GATES
                or gate_id in seen
                or gate.get("passed") is not True
            ):
                raise ValueError("Agent/ART security gate failed or is duplicated")
            _validate_digest(gate.get("receipt_sha256"), "security gate receipt")
            seen.add(str(gate_id))
        if seen != REQUIRED_SECURITY_GATES:
            raise ValueError("security assessment is missing a required gate")

    def _validate_audit_chain(self) -> None:
        audit = self.audit_chain
        events = audit.get("events")
        if (
            audit.get("verified_by_coordinator") is not True
            or audit.get("truncated") is not False
            or not isinstance(events, list)
            or not events
            or audit.get("event_count") != len(events)
        ):
            raise ValueError("audit chain is incomplete or not coordinator-verified")
        previous = ZERO_HASH
        seen: set[str] = set()
        for event in events:
            if not isinstance(event, dict):
                raise ValueError("audit event is invalid")
            event_hash = _validate_digest(event.get("event_hash"), "audit event hash")
            if event.get("previous_hash") != previous or event_hash in seen:
                raise ValueError("audit chain linkage is invalid")
            seen.add(event_hash)
            previous = event_hash
        if previous != audit.get("head_sha256"):
            raise ValueError("audit chain head does not match the final event")

    def _validate_model_release(self) -> None:
        bindings = {
            "job_id": self.job_id,
            "contract_sha256": self.contract_sha256,
            "model_sha256": self.model_sha256,
        }
        for key, expected in bindings.items():
            if self.model_release.get(key) != expected:
                raise ValueError(f"model_release {key} does not match the package")
        if (
            self.model_release.get("algorithm") != "Ed25519"
            or self.model_release.get("verified") is not True
            or not SHA256_RE.fullmatch(
                str(self.model_release.get("manifest_sha256", ""))
            )
            or not SHA256_RE.fullmatch(
                str(self.model_release.get("key_fingerprint_sha256", ""))
            )
        ):
            raise ValueError("model_release must contain a verified Ed25519 receipt")
        try:
            release_key = serialization.load_pem_public_key(
                self.model_release_public_key_pem.encode("ascii")
            )
        except (UnicodeEncodeError, TypeError, ValueError) as exc:
            raise ValueError("model release public key is invalid") from exc
        if not isinstance(release_key, Ed25519PublicKey):
            raise ValueError("model release public key must be Ed25519")
        if _public_fingerprint(release_key) != self.model_release[
            "key_fingerprint_sha256"
        ]:
            raise ValueError("model release public key fingerprint does not match")
        try:
            release_manifest = ModelReleaseManifest(
                job_id=self.job_id,
                external_job_id=str(self.model_release["external_job_id"]),
                contract_sha256=self.contract_sha256,
                model_sha256=self.model_sha256,
                model_file_name=str(self.model_release["model_file_name"]),
                approved_at=str(self.model_release["approved_at"]),
            )
            if (
                hashlib.sha256(release_manifest.canonical_bytes()).hexdigest()
                != self.model_release["manifest_sha256"]
            ):
                raise ValueError("model release manifest digest does not match")
            release_key.verify(
                _decode_signature(str(self.model_release["signature"])),
                release_manifest.canonical_bytes(),
            )
        except (InvalidSignature, KeyError, ValueError) as exc:
            raise ValueError("model release signature did not verify") from exc


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_file():
        raise EvidencePackageError("Evidence signing key must be a regular non-symlink file")
    if stat.S_IMODE(resolved.stat().st_mode) & 0o077:
        raise EvidencePackageError("Evidence signing key permissions must be 0600 or stricter")
    try:
        key = serialization.load_pem_private_key(resolved.read_bytes(), password=None)
    except (OSError, TypeError, ValueError) as exc:
        raise EvidencePackageError("Unable to load evidence signing key") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise EvidencePackageError("Evidence signing key must be Ed25519")
    return key


def _standalone_verifier_bytes() -> bytes:
    path = Path(__file__).with_name("standalone_verifier.py")
    try:
        script = path.read_bytes()
    except OSError as exc:
        raise EvidencePackageError("Standalone verifier source is unavailable") from exc
    if not script.startswith(b"#!/usr/bin/env python3\n"):
        raise EvidencePackageError("Standalone verifier is not executable source")
    return script


def _document_payloads(source: EvidencePackageSource) -> dict[str, bytes]:
    approvals = {
        "schema_version": "rarelink-approvals-v1",
        "approvals": [
            item.model_dump(mode="json") for item in source.approvals
        ],
        "required_approval_count": 2,
        "distinct_approvers_verified": True,
    }
    cards = {item.site_id: item for item in source.site_data_cards}
    receipts = {item.site_id: item for item in source.site_receipts}
    data_fingerprints = {
        site: cards[site].dataset_fingerprint for site in source.expected_sites
    }
    payloads: dict[str, bytes] = {
        "study-contract.json": _canonical_json(source.study_contract),
        "approvals.json": _canonical_json(approvals),
        "aggregate-metrics.json": _canonical_json(source.aggregate_metrics),
        "privacy-ledger.json": _canonical_json(source.privacy_ledger),
        "security-assessment.json": _canonical_json(source.security_assessment),
        "audit-chain.json": _canonical_json(source.audit_chain),
        "global-model-manifest.json": _canonical_json(source.model_release),
        "model-release-public-key.pem": source.model_release_public_key_pem.encode(
            "ascii"
        ),
        "verify-evidence-package": _standalone_verifier_bytes(),
    }
    for site in source.expected_sites:
        payloads[f"site-data-cards/{site}.json"] = _canonical_json(
            cards[site].model_dump(mode="json")
        )
        payloads[f"site-receipts/{site}.json"] = _canonical_json(
            receipts[site].model_dump(mode="json")
        )
    payloads["model-card.json"] = _canonical_json(
        {
            "schema_version": "rarelink-model-card-v2",
            "study_id": source.study_id,
            "job_id": source.job_id,
            "model_sha256": source.model_sha256,
            "contract_sha256": source.contract_sha256,
            "code_sha256": source.code_sha256,
            "intended_use": "approved multi-centre research only",
            "diagnostic_use_approved": False,
            "clinical_validity_claimed": False,
            "limitations": source.limitations,
        }
    )
    payloads["run-card.json"] = _canonical_json(
        {
            "schema_version": "rarelink-run-card-v2",
            "study_id": source.study_id,
            "job_id": source.job_id,
            "contract_sha256": source.contract_sha256,
            "bundle_sha256": source.bundle_sha256,
            "code_sha256": source.code_sha256,
            "model_sha256": source.model_sha256,
            "expected_sites": source.expected_sites,
            "site_dataset_fingerprints": data_fingerprints,
            "completed_site_count": 3,
            "quorum_required": 3,
            "completion_status": "COMPLETED_3_OF_3",
            "evidence_level": source.evidence_level,
            "generated_at": _safe_timestamp(source.generated_at),
            "patient_data_exported": False,
            "secret_exported": False,
            "local_paths_exported": False,
        }
    )
    payloads["report.md"] = (
        "# RareLink Research Evidence Package\n\n"
        f"- Study: `{source.study_id}`\n"
        f"- Physical job: `{source.job_id}`\n"
        f"- Evidence level: `{source.evidence_level}`\n"
        "- Completion: `3/3 expected sites completed`\n"
        f"- Contract SHA-256: `{source.contract_sha256}`\n"
        f"- Code SHA-256: `{source.code_sha256}`\n"
        f"- Model SHA-256: `{source.model_sha256}`\n\n"
        "The package signature protects the complete exported evidence set. The "
        "offline verifier checks the external signer trust anchor, all file "
        "digests, two-person approval separation, three-site completion, privacy "
        "budget, Agent/ART gates, audit linkage, and the global model signature.\n\n"
        "Audit event HMAC values are not recomputed offline because the coordinator "
        "HMAC key is intentionally not exported. Offline verification checks the "
        "complete linkage and coordinator verification assertion; the package "
        "Ed25519 signature prevents post-export modification.\n\n"
        "This package contains aggregate research evidence only. It contains no "
        "source medical images, patient identifiers, local paths, credentials, "
        "private keys, or individual model updates.\n\n"
        "## Limitations\n\n"
        + "".join(f"- {item}\n" for item in source.limitations)
    ).encode("utf-8")
    expected = ROOT_PAYLOAD_FILES | {
        *(f"site-data-cards/{site}.json" for site in source.expected_sites),
        *(f"site-receipts/{site}.json" for site in source.expected_sites),
    }
    if set(payloads) != expected:
        raise EvidencePackageError("Evidence payload set is incomplete")
    return payloads


def _manifest(source: EvidencePackageSource, payloads: dict[str, bytes]) -> dict[str, Any]:
    return {
        "schema_version": "rarelink-evidence-package-manifest-v2",
        "study_id": source.study_id,
        "job_id": source.job_id,
        "contract_sha256": source.contract_sha256,
        "bundle_sha256": source.bundle_sha256,
        "code_sha256": source.code_sha256,
        "model_sha256": source.model_sha256,
        "expected_sites": source.expected_sites,
        "evidence_level": source.evidence_level,
        "generated_at": _safe_timestamp(source.generated_at),
        "files": [
            {
                "path": name,
                "sha256": _sha256_bytes(payloads[name]),
                "size_bytes": len(payloads[name]),
            }
            for name in sorted(payloads)
        ],
        "completed_site_count": 3,
        "quorum_required": 3,
        "patient_data_included": False,
        "secret_included": False,
        "private_key_included": False,
        "claim_boundary": (
            "Offline verification proves package integrity and exported evidence "
            "consistency. It does not independently establish clinical validity."
        ),
    }


def _zip_write(
    archive: zipfile.ZipFile,
    name: str,
    data: bytes,
    *,
    executable: bool = False,
) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    permissions = 0o755 if executable else 0o644
    info.external_attr = (stat.S_IFREG | permissions) << 16
    archive.writestr(info, data)


def build_evidence_package(
    source: EvidencePackageSource,
    *,
    output_path: Path,
    private_key_path: Path,
) -> dict[str, Any]:
    """Create a deterministic-format ZIP signed by a coordinator-local key."""
    output = output_path.resolve()
    if output_path.is_symlink() or output.suffix.lower() != ".zip":
        raise EvidencePackageError("Evidence package output must be a non-symlink .zip file")
    output.parent.mkdir(parents=True, exist_ok=True)
    key = _load_private_key(private_key_path)
    payloads = _document_payloads(source)
    manifest = _manifest(source, payloads)
    manifest_bytes = _canonical_json(manifest)
    canonical = DOMAIN_SEPARATOR + manifest_bytes
    public_key = key.public_key()
    signature_receipt = {
        "schema_version": "rarelink-evidence-package-signature-v2",
        "algorithm": "Ed25519",
        "manifest_sha256": _sha256_bytes(canonical),
        "key_fingerprint_sha256": _public_fingerprint(public_key),
        "signature": base64.urlsafe_b64encode(key.sign(canonical))
        .rstrip(b"=")
        .decode("ascii"),
        "private_key_exported": False,
    }
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with tempfile.NamedTemporaryFile(
        prefix=".rarelink-evidence-",
        suffix=".zip",
        dir=output.parent,
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(temporary_path, "w") as archive:
            for name in sorted(payloads):
                _zip_write(
                    archive,
                    name,
                    payloads[name],
                    executable=name == "verify-evidence-package",
                )
            _zip_write(archive, "manifest.json", manifest_bytes)
            _zip_write(archive, "signature.json", _canonical_json(signature_receipt))
            _zip_write(archive, "signer-public-key.pem", public_pem)
        os.chmod(temporary_path, 0o640)
        if temporary_path.stat().st_size > MAX_PACKAGE_BYTES:
            raise EvidencePackageError("Evidence package exceeds the size limit")
        os.replace(temporary_path, output)
    finally:
        temporary_path.unlink(missing_ok=True)
    return {
        "schema_version": "rarelink-evidence-package-build-v2",
        "package_file_name": output.name,
        "package_sha256": _sha256_bytes(output.read_bytes()),
        "manifest_sha256": signature_receipt["manifest_sha256"],
        "key_fingerprint_sha256": signature_receipt["key_fingerprint_sha256"],
        "evidence_level": source.evidence_level,
        "completed_site_count": 3,
        "file_count": len(payloads),
        "verified": True,
        "patient_data_exported": False,
        "private_key_exported": False,
        "local_path_exported": False,
    }


def verify_evidence_package(
    package_path: Path,
    *,
    expected_key_fingerprint_sha256: str,
) -> dict[str, Any]:
    """Run the same strict semantic and cryptographic checks as the embedded verifier."""
    try:
        return standalone_verify(package_path, expected_key_fingerprint_sha256)
    except (StandaloneVerificationError, OSError) as exc:
        raise EvidencePackageError(str(exc)) from exc
