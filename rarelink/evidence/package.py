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
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import BaseModel, Field, field_validator, model_validator

from rarelink.security.model_signing import ModelReleaseManifest
from rarelink.services.physical_results import parse_aggregate_metrics

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$")
DOMAIN_SEPARATOR = b"RareLink research evidence package v1\x00"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_BYTES = 32 * 1024 * 1024
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
DOCUMENT_FILES = {
    "study-contract.json": "study_contract",
    "site-receipts.json": "site_receipts",
    "aggregate-metrics.json": "aggregate_metrics",
    "privacy-ledger.json": "privacy_ledger",
    "security-assessment.json": "security_assessment",
    "audit-chain.json": "audit_chain",
    "global-model-manifest.json": "model_release",
}
GENERATED_FILES = {
    "data-card.json",
    "model-release-public-key.pem",
    "model-card.json",
    "run-card.json",
    "report.md",
}
PACKAGE_FILES = set(DOCUMENT_FILES) | GENERATED_FILES


class EvidencePackageError(ValueError):
    """Evidence was unsafe, internally inconsistent, or cryptographically invalid."""


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


def _validate_digest(value: str, label: str) -> str:
    if not SHA256_RE.fullmatch(value):
        raise EvidencePackageError(f"{label} must be a lowercase SHA-256 digest")
    return value


class EvidencePackageSource(BaseModel):
    """Allow-listed material used to create one immutable research evidence release."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["rarelink-evidence-source-v1"]
    study_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$")
    job_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$")
    contract_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_sites: list[str] = Field(min_length=3, max_length=3)
    evidence_level: Literal["L2", "L3", "L4"]
    generated_at: datetime
    study_contract: dict[str, Any]
    site_receipts: list[dict[str, Any]] = Field(min_length=3, max_length=3)
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
    def validate_bindings_and_safety(self) -> EvidencePackageSource:
        for value in (
            self.study_contract,
            self.site_receipts,
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
        receipt_sites = [item.get("site_id") for item in self.site_receipts]
        if len(set(receipt_sites)) != 3 or set(receipt_sites) != set(self.expected_sites):
            raise ValueError("site_receipts must cover every expected site exactly once")
        for receipt in self.site_receipts:
            _validate_digest(str(receipt.get("receipt_sha256", "")), "site receipt")
            fingerprint = receipt.get("dataset_fingerprint")
            if fingerprint is not None:
                _validate_digest(str(fingerprint), "dataset fingerprint")
        parse_aggregate_metrics(
            self.aggregate_metrics,
            (self.expected_sites[0], self.expected_sites[1], self.expected_sites[2]),
        )
        if self.study_contract.get("contract_sha256") != self.contract_sha256:
            raise ValueError("study_contract does not match the package contract")
        audit_head = self.audit_chain.get("head_sha256")
        if (
            self.audit_chain.get("verified") is not True
            or not isinstance(audit_head, str)
            or not SHA256_RE.fullmatch(audit_head)
        ):
            raise ValueError("audit_chain must contain a verified SHA-256 head")
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
            or not re.fullmatch(
                r"[A-Za-z0-9_-]{80,100}",
                str(self.model_release.get("signature", "")),
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
        if (
            _public_fingerprint(release_key)
            != self.model_release["key_fingerprint_sha256"]
        ):
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
        return self


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


def _public_fingerprint(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return _sha256_bytes(raw)


def _document_payloads(source: EvidencePackageSource) -> dict[str, bytes]:
    payloads = {
        file_name: _canonical_json(getattr(source, source_field))
        for file_name, source_field in DOCUMENT_FILES.items()
    }
    site_receipts = {
        item["site_id"]: item for item in source.site_receipts
    }
    payloads["model-release-public-key.pem"] = (
        source.model_release_public_key_pem.encode("ascii")
    )
    payloads["data-card.json"] = _canonical_json(
        {
            "schema_version": "rarelink-data-card-v1",
            "study_id": source.study_id,
            "expected_sites": source.expected_sites,
            "site_dataset_fingerprints": {
                site: site_receipts[site].get("dataset_fingerprint")
                for site in source.expected_sites
            },
            "source_data_exported": False,
            "case_identifiers_exported": False,
            "local_paths_exported": False,
            "limitations": source.limitations,
        }
    )
    payloads["model-card.json"] = _canonical_json(
        {
            "schema_version": "rarelink-model-card-v1",
            "study_id": source.study_id,
            "job_id": source.job_id,
            "model_sha256": source.model_sha256,
            "contract_sha256": source.contract_sha256,
            "intended_use": "approved multi-centre research only",
            "diagnostic_use_approved": False,
            "clinical_validity_claimed": False,
            "limitations": source.limitations,
        }
    )
    payloads["run-card.json"] = _canonical_json(
        {
            "schema_version": "rarelink-run-card-v1",
            "study_id": source.study_id,
            "job_id": source.job_id,
            "contract_sha256": source.contract_sha256,
            "bundle_sha256": source.bundle_sha256,
            "model_sha256": source.model_sha256,
            "expected_sites": source.expected_sites,
            "quorum_required": 3,
            "evidence_level": source.evidence_level,
            "generated_at": _safe_timestamp(source.generated_at),
            "patient_data_exported": False,
            "secret_exported": False,
        }
    )
    payloads["report.md"] = (
        "# RareLink Research Evidence Package\n\n"
        f"- Study: `{source.study_id}`\n"
        f"- Physical job: `{source.job_id}`\n"
        f"- Evidence level: `{source.evidence_level}`\n"
        f"- Expected sites: `{', '.join(source.expected_sites)}`\n"
        f"- Contract SHA-256: `{source.contract_sha256}`\n"
        f"- Model SHA-256: `{source.model_sha256}`\n\n"
        "This package contains aggregate research evidence only. It contains no "
        "source medical images, patient identifiers, local paths, credentials, "
        "private keys, or individual model updates.\n\n"
        "## Limitations\n\n"
        + "".join(f"- {item}\n" for item in source.limitations)
    ).encode("utf-8")
    return payloads


def _manifest(source: EvidencePackageSource, payloads: dict[str, bytes]) -> dict[str, Any]:
    return {
        "schema_version": "rarelink-evidence-package-manifest-v1",
        "study_id": source.study_id,
        "job_id": source.job_id,
        "contract_sha256": source.contract_sha256,
        "bundle_sha256": source.bundle_sha256,
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
        "patient_data_included": False,
        "secret_included": False,
        "private_key_included": False,
        "claim_boundary": (
            "The evidence level records the supplied verified environment. "
            "L2 is isolated integration and is not three-physical-site evidence."
        ),
    }


def _zip_write(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    archive.writestr(info, data)


def build_evidence_package(
    source: EvidencePackageSource,
    *,
    output_path: Path,
    private_key_path: Path,
) -> dict[str, Any]:
    """Create one deterministic-format ZIP signed by a coordinator-local key."""
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
    signature = key.sign(canonical)
    signature_receipt = {
        "schema_version": "rarelink-evidence-package-signature-v1",
        "algorithm": "Ed25519",
        "manifest_sha256": _sha256_bytes(canonical),
        "key_fingerprint_sha256": _public_fingerprint(public_key),
        "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii"),
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
                _zip_write(archive, name, payloads[name])
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
        "schema_version": "rarelink-evidence-package-build-v1",
        "package_file_name": output.name,
        "package_sha256": _sha256_bytes(output.read_bytes()),
        "manifest_sha256": signature_receipt["manifest_sha256"],
        "key_fingerprint_sha256": signature_receipt["key_fingerprint_sha256"],
        "evidence_level": source.evidence_level,
        "file_count": len(payloads),
        "verified": True,
        "patient_data_exported": False,
        "private_key_exported": False,
        "local_path_exported": False,
    }


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


def _safe_archive_names(archive: zipfile.ZipFile) -> list[str]:
    names: list[str] = []
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        mode = info.external_attr >> 16
        if (
            info.is_dir()
            or path.is_absolute()
            or ".." in path.parts
            or len(path.parts) != 1
            or stat.S_ISLNK(mode)
        ):
            raise EvidencePackageError("Evidence package contains an unsafe archive entry")
        if info.file_size > MAX_JSON_BYTES:
            raise EvidencePackageError("Evidence package entry exceeds the size limit")
        names.append(info.filename)
    if len(names) != len(set(names)):
        raise EvidencePackageError("Evidence package contains duplicate entries")
    return names


def verify_evidence_package(
    package_path: Path,
    *,
    expected_key_fingerprint_sha256: str,
) -> dict[str, Any]:
    """Verify archive safety, every file digest, the signature, and trust anchor."""
    _validate_digest(expected_key_fingerprint_sha256, "expected key fingerprint")
    path = package_path.resolve()
    if package_path.is_symlink() or not path.is_file():
        raise EvidencePackageError("Evidence package must be a regular non-symlink file")
    if path.stat().st_size > MAX_PACKAGE_BYTES:
        raise EvidencePackageError("Evidence package exceeds the size limit")
    expected_archive_files = PACKAGE_FILES | {
        "manifest.json",
        "signature.json",
        "signer-public-key.pem",
    }
    try:
        with zipfile.ZipFile(path) as archive:
            names = _safe_archive_names(archive)
            if set(names) != expected_archive_files:
                raise EvidencePackageError("Evidence package file set is incomplete or unexpected")
            manifest_bytes = archive.read("manifest.json")
            signature_receipt = json.loads(archive.read("signature.json"))
            manifest = json.loads(manifest_bytes)
            public_pem = archive.read("signer-public-key.pem")
            documents = {name: archive.read(name) for name in PACKAGE_FILES}
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise EvidencePackageError("Evidence package cannot be parsed") from exc
    if _canonical_json(manifest) != manifest_bytes:
        raise EvidencePackageError("Evidence manifest is not canonical JSON")
    if manifest.get("schema_version") != "rarelink-evidence-package-manifest-v1":
        raise EvidencePackageError("Evidence manifest schema is unsupported")
    if (
        manifest.get("patient_data_included") is not False
        or manifest.get("secret_included") is not False
        or manifest.get("private_key_included") is not False
    ):
        raise EvidencePackageError("Evidence manifest does not assert a safe boundary")
    listed = manifest.get("files")
    if not isinstance(listed, list) or len(listed) != len(PACKAGE_FILES):
        raise EvidencePackageError("Evidence manifest file list is invalid")
    listed_names: set[str] = set()
    for entry in listed:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size_bytes"}:
            raise EvidencePackageError("Evidence manifest file entry is invalid")
        name = entry["path"]
        if name not in PACKAGE_FILES or name in listed_names:
            raise EvidencePackageError("Evidence manifest contains an invalid file path")
        listed_names.add(name)
        content = documents[name]
        if (
            entry["sha256"] != _sha256_bytes(content)
            or entry["size_bytes"] != len(content)
        ):
            raise EvidencePackageError("Evidence package file digest does not match")
        if name.endswith(".json"):
            try:
                _reject_sensitive(json.loads(content))
            except json.JSONDecodeError as exc:
                raise EvidencePackageError("Evidence JSON document is invalid") from exc
    if listed_names != PACKAGE_FILES:
        raise EvidencePackageError("Evidence manifest does not cover every document")
    try:
        public_key = serialization.load_pem_public_key(public_pem)
    except (TypeError, ValueError) as exc:
        raise EvidencePackageError("Evidence public key is invalid") from exc
    if not isinstance(public_key, Ed25519PublicKey):
        raise EvidencePackageError("Evidence public key must be Ed25519")
    actual_fingerprint = _public_fingerprint(public_key)
    if actual_fingerprint != expected_key_fingerprint_sha256:
        raise EvidencePackageError("Evidence signer fingerprint does not match trust policy")
    canonical = DOMAIN_SEPARATOR + manifest_bytes
    if (
        not isinstance(signature_receipt, dict)
        or signature_receipt.get("schema_version")
        != "rarelink-evidence-package-signature-v1"
        or signature_receipt.get("algorithm") != "Ed25519"
        or signature_receipt.get("manifest_sha256") != _sha256_bytes(canonical)
        or signature_receipt.get("key_fingerprint_sha256") != actual_fingerprint
        or signature_receipt.get("private_key_exported") is not False
    ):
        raise EvidencePackageError("Evidence signature receipt is invalid")
    try:
        public_key.verify(
            _decode_signature(str(signature_receipt.get("signature", ""))),
            canonical,
        )
    except InvalidSignature as exc:
        raise EvidencePackageError("Evidence package signature is invalid") from exc
    try:
        model_release = json.loads(documents["global-model-manifest.json"])
        model_release_key = serialization.load_pem_public_key(
            documents["model-release-public-key.pem"]
        )
        if not isinstance(model_release_key, Ed25519PublicKey):
            raise EvidencePackageError("Model release public key must be Ed25519")
        if (
            _public_fingerprint(model_release_key)
            != model_release.get("key_fingerprint_sha256")
        ):
            raise EvidencePackageError("Model release key fingerprint does not match")
        model_release_manifest = ModelReleaseManifest(
            job_id=str(model_release["job_id"]),
            external_job_id=str(model_release["external_job_id"]),
            contract_sha256=str(model_release["contract_sha256"]),
            model_sha256=str(model_release["model_sha256"]),
            model_file_name=str(model_release["model_file_name"]),
            approved_at=str(model_release["approved_at"]),
        )
        if (
            hashlib.sha256(model_release_manifest.canonical_bytes()).hexdigest()
            != model_release.get("manifest_sha256")
        ):
            raise EvidencePackageError("Model release manifest digest does not match")
        model_release_key.verify(
            _decode_signature(str(model_release["signature"])),
            model_release_manifest.canonical_bytes(),
        )
    except (
        InvalidSignature,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise EvidencePackageError("Global model release signature is invalid") from exc
    return {
        "schema_version": "rarelink-evidence-package-verification-v1",
        "package_sha256": _sha256_bytes(path.read_bytes()),
        "manifest_sha256": _sha256_bytes(canonical),
        "key_fingerprint_sha256": actual_fingerprint,
        "study_id": manifest.get("study_id"),
        "job_id": manifest.get("job_id"),
        "evidence_level": manifest.get("evidence_level"),
        "file_count": len(PACKAGE_FILES),
        "verified": True,
        "trust_anchor_matched": True,
        "model_release_signature_verified": True,
        "patient_data_exported": False,
        "private_key_exported": False,
        "local_path_exported": False,
        "claim_boundary": manifest.get("claim_boundary"),
    }
