#!/usr/bin/env python3
"""Standalone offline verifier embedded in RareLink evidence packages.

This file intentionally depends only on Python's standard library and
``cryptography``. It must not import the RareLink application.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import re
import stat
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from statistics import fmean, pstdev
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DOMAIN_SEPARATOR = b"RareLink research evidence package v2\x00"
MODEL_DOMAIN_SEPARATOR = b"RareLink global model release v1\x00"
MAX_ENTRY_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_BYTES = 32 * 1024 * 1024
ZERO_HASH = "0" * 64
SUPPORT_FILES = {
    "manifest.json",
    "signature.json",
    "signer-public-key.pem",
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


class VerificationError(ValueError):
    """The evidence package failed a mandatory offline check."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise VerificationError(f"{label} is not a lowercase SHA-256 digest")
    return value


def _decode_signature(value: Any) -> bytes:
    if not isinstance(value, str):
        raise VerificationError("signature is not text")
    try:
        decoded = base64.urlsafe_b64decode(
            (value + "=" * (-len(value) % 4)).encode("ascii")
        )
    except (UnicodeEncodeError, ValueError) as exc:
        raise VerificationError("signature encoding is invalid") from exc
    if len(decoded) != 64:
        raise VerificationError("signature length is invalid")
    return decoded


def _fingerprint(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return _sha256(raw)


def _reject_sensitive(value: Any, trail: tuple[str, ...] = ()) -> None:
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
                raise VerificationError(
                    f"forbidden field found at {'.'.join((*trail, key))}"
                )
            _reject_sensitive(child, (*trail, key))
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive(child, (*trail, str(index)))
        return
    if isinstance(value, str):
        stripped = value.strip()
        if (
            stripped.startswith(("/", "~/", "\\\\"))
            or re.match(r"^[A-Za-z]:[\\/]", stripped)
            or "-----BEGIN PRIVATE KEY-----" in stripped
        ):
            raise VerificationError("local path or private key found")


def _expected_payload_files(sites: list[str]) -> set[str]:
    return ROOT_PAYLOAD_FILES | {
        *(f"site-data-cards/{site}.json" for site in sites),
        *(f"site-receipts/{site}.json" for site in sites),
    }


def _read_zip(path: Path) -> tuple[dict[str, bytes], list[zipfile.ZipInfo]]:
    if path.is_symlink() or not path.is_file():
        raise VerificationError("package must be a regular non-symlink ZIP")
    if path.stat().st_size > MAX_PACKAGE_BYTES:
        raise VerificationError("package exceeds size limit")
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names: list[str] = []
            documents: dict[str, bytes] = {}
            for info in infos:
                pure = PurePosixPath(info.filename)
                mode = info.external_attr >> 16
                if (
                    info.is_dir()
                    or pure.is_absolute()
                    or ".." in pure.parts
                    or len(pure.parts) > 2
                    or stat.S_ISLNK(mode)
                    or info.file_size > MAX_ENTRY_BYTES
                ):
                    raise VerificationError("unsafe ZIP entry")
                names.append(info.filename)
                documents[info.filename] = archive.read(info.filename)
            if len(names) != len(set(names)):
                raise VerificationError("duplicate ZIP entry")
            return documents, infos
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise VerificationError("package cannot be parsed") from exc


def _load_json(documents: dict[str, bytes], name: str) -> dict[str, Any]:
    try:
        value = json.loads(documents[name])
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"{name} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{name} must contain an object")
    _reject_sensitive(value)
    return value


def _verify_aggregate_metrics(metrics: dict[str, Any], sites: list[str]) -> None:
    rows = metrics.get("sites")
    if not isinstance(rows, list) or len(rows) != 3:
        raise VerificationError("aggregate metrics do not contain three sites")
    if {row.get("site_id") for row in rows if isinstance(row, dict)} != set(sites):
        raise VerificationError("aggregate metrics site set does not match")
    try:
        dice = [float(row["dice"]) for row in rows]
        hd95 = [float(row["hd95"]) for row in rows]
    except (KeyError, TypeError, ValueError) as exc:
        raise VerificationError("aggregate metrics are malformed") from exc
    if (
        any(not math.isfinite(value) or not 0 <= value <= 1 for value in dice)
        or any(not math.isfinite(value) or value < 0 for value in hd95)
        or not math.isclose(float(metrics["mean_dice"]), fmean(dice), abs_tol=1e-6)
        or not math.isclose(float(metrics["worst_site_dice"]), min(dice), abs_tol=1e-6)
        or not math.isclose(float(metrics["site_dice_std"]), pstdev(dice), abs_tol=1e-6)
        or not math.isclose(float(metrics["hd95"]), fmean(hd95), abs_tol=1e-6)
    ):
        raise VerificationError("aggregate metrics cannot be recomputed")


def _verify_model_release(
    release: dict[str, Any],
    public_pem: bytes,
    *,
    job_id: str,
    contract_sha256: str,
    model_sha256: str,
) -> None:
    for key, expected in {
        "job_id": job_id,
        "contract_sha256": contract_sha256,
        "model_sha256": model_sha256,
    }.items():
        if release.get(key) != expected:
            raise VerificationError(f"global model {key} binding failed")
    model_file_name = release.get("model_file_name")
    if (
        release.get("algorithm") != "Ed25519"
        or release.get("verified") is not True
        or release.get("private_key_exported") is not False
        or not isinstance(model_file_name, str)
        or Path(model_file_name).name != model_file_name
        or model_file_name in {"", ".", ".."}
    ):
        raise VerificationError("global model release safety assertion failed")
    try:
        public_key = serialization.load_pem_public_key(public_pem)
    except (TypeError, ValueError) as exc:
        raise VerificationError("model release public key is invalid") from exc
    if not isinstance(public_key, Ed25519PublicKey):
        raise VerificationError("model release key is not Ed25519")
    if _fingerprint(public_key) != release.get("key_fingerprint_sha256"):
        raise VerificationError("model release key fingerprint failed")
    normalized = {
        "schema_version": "rarelink-model-release-manifest-v1",
        "job_id": release.get("job_id"),
        "external_job_id": release.get("external_job_id"),
        "contract_sha256": release.get("contract_sha256"),
        "model_sha256": release.get("model_sha256"),
        "model_file_name": release.get("model_file_name"),
        "approved_at": release.get("approved_at"),
    }
    try:
        approved_at = datetime.fromisoformat(
            str(normalized["approved_at"]).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise VerificationError("model approval time is invalid") from exc
    if approved_at.tzinfo is None:
        raise VerificationError("model approval time has no timezone")
    normalized["approved_at"] = (
        approved_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    )
    canonical = MODEL_DOMAIN_SEPARATOR + json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    if _sha256(canonical) != release.get("manifest_sha256"):
        raise VerificationError("model release manifest digest failed")
    try:
        public_key.verify(_decode_signature(release.get("signature")), canonical)
    except InvalidSignature as exc:
        raise VerificationError("model release signature failed") from exc


def _verify_audit_chain(audit: dict[str, Any]) -> None:
    events = audit.get("events")
    if (
        audit.get("verified_by_coordinator") is not True
        or audit.get("truncated") is not False
        or not isinstance(events, list)
        or not events
        or audit.get("event_count") != len(events)
    ):
        raise VerificationError("audit chain completeness assertion failed")
    previous = ZERO_HASH
    seen: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            raise VerificationError("audit event is malformed")
        event_hash = _digest(event.get("event_hash"), "audit event hash")
        if not isinstance(event.get("event_id"), str) or not isinstance(
            event.get("event_type"), str
        ):
            raise VerificationError("audit event identity is missing")
        if event.get("previous_hash") != previous or event_hash in seen:
            raise VerificationError("audit chain linkage failed")
        seen.add(event_hash)
        previous = event_hash
    if previous != audit.get("head_sha256"):
        raise VerificationError("audit chain head failed")


def _verify_semantics(documents: dict[str, bytes], manifest: dict[str, Any]) -> None:
    sites = manifest.get("expected_sites")
    if not isinstance(sites, list) or len(sites) != 3 or len(set(sites)) != 3:
        raise VerificationError("manifest does not require three distinct sites")
    contract_sha = _digest(manifest.get("contract_sha256"), "contract hash")
    bundle_sha = _digest(manifest.get("bundle_sha256"), "bundle hash")
    code_sha = _digest(manifest.get("code_sha256"), "code hash")
    model_sha = _digest(manifest.get("model_sha256"), "model hash")
    job_id = manifest.get("job_id")

    contract = _load_json(documents, "study-contract.json")
    if (
        contract.get("contract_sha256") != contract_sha
        or contract.get("bundle_sha256") != bundle_sha
        or contract.get("code_sha256") != code_sha
        or contract.get("expected_sites") != sites
        or contract.get("quorum_required") != 3
    ):
        raise VerificationError("study contract binding failed")
    total_rounds = contract.get("total_rounds")
    if not isinstance(total_rounds, int) or total_rounds < 1:
        raise VerificationError("study contract round count is invalid")

    approvals = _load_json(documents, "approvals.json").get("approvals")
    if not isinstance(approvals, list) or len(approvals) != 2:
        raise VerificationError("exactly two approvals are required")
    if (
        len({item.get("approver_id") for item in approvals}) != 2
        or {item.get("approval_type") for item in approvals}
        != {"study-release", "independent-review"}
        or any(item.get("approved") is not True for item in approvals)
        or any(item.get("contract_sha256") != contract_sha for item in approvals)
        or any(
            not SHA256_RE.fullmatch(str(item.get("approval_receipt_sha256", "")))
            for item in approvals
        )
    ):
        raise VerificationError("two-person approval separation failed")

    data_fingerprints: dict[str, str] = {}
    for site in sites:
        card = _load_json(documents, f"site-data-cards/{site}.json")
        fingerprint = _digest(card.get("dataset_fingerprint"), "dataset fingerprint")
        if (
            card.get("site_id") != site
            or not SHA256_RE.fullmatch(str(card.get("manifest_sha256", "")))
            or not isinstance(card.get("case_count"), int)
            or card.get("case_count") < 1
            or set(card.get("modalities", [])) != {"T1", "T1ce", "T2", "FLAIR"}
            or card.get("quality_passed") is not True
            or card.get("source_data_exported") is not False
            or card.get("case_identifiers_exported") is not False
            or card.get("local_paths_exported") is not False
        ):
            raise VerificationError(f"site data card failed for {site}")
        data_fingerprints[site] = fingerprint

        receipt = _load_json(documents, f"site-receipts/{site}.json")
        if (
            receipt.get("site_id") != site
            or not SHA256_RE.fullmatch(str(receipt.get("receipt_sha256", "")))
            or receipt.get("job_id") != job_id
            or receipt.get("contract_sha256") != contract_sha
            or receipt.get("code_sha256") != code_sha
            or receipt.get("dataset_fingerprint") != fingerprint
            or receipt.get("state") != "COMPLETED"
            or receipt.get("completed_round") != total_rounds
            or receipt.get("total_rounds") != total_rounds
            or receipt.get("signature_verified_by_coordinator") is not True
        ):
            raise VerificationError(f"3/3 completion or receipt binding failed for {site}")

    run = _load_json(documents, "run-card.json")
    if (
        run.get("completed_site_count") != 3
        or run.get("quorum_required") != 3
        or run.get("completion_status") != "COMPLETED_3_OF_3"
        or run.get("code_sha256") != code_sha
        or run.get("model_sha256") != model_sha
        or run.get("site_dataset_fingerprints") != data_fingerprints
    ):
        raise VerificationError("run card completion binding failed")

    privacy = _load_json(documents, "privacy-ledger.json")
    if (
        privacy.get("budget_exceeded") is not False
        or privacy.get("status") not in {"WITHIN_BUDGET", "NOT_APPLICABLE"}
    ):
        raise VerificationError("privacy budget gate failed")
    if privacy.get("enabled") is True:
        maximum = privacy.get("maximum_epsilon")
        delta = privacy.get("delta")
        rows = privacy.get("sites")
        if (
            not isinstance(maximum, int | float)
            or isinstance(maximum, bool)
            or maximum <= 0
            or not isinstance(delta, int | float)
            or isinstance(delta, bool)
            or not 0 < delta < 1
            or not isinstance(rows, list)
            or len(rows) != 3
            or {row.get("site_id") for row in rows if isinstance(row, dict)}
            != set(sites)
            or any(float(row.get("epsilon", math.inf)) > float(maximum) for row in rows)
            or any(float(row.get("epsilon", -1)) < 0 for row in rows)
            or any(
                not SHA256_RE.fullmatch(str(row.get("receipt_sha256", "")))
                for row in rows
            )
        ):
            raise VerificationError("site DP accounting gate failed")
    elif privacy.get("enabled") is not False or privacy.get("status") != "NOT_APPLICABLE":
        raise VerificationError("disabled DP accounting status is inconsistent")

    security = _load_json(documents, "security-assessment.json")
    gates = security.get("gates")
    required_gates = {
        "agent_redteam",
        "art_membership_inference",
        "art_model_inversion",
        "update_guard",
    }
    if (
        security.get("all_required_gates_passed") is not True
        or not isinstance(gates, list)
        or {gate.get("gate_id") for gate in gates if isinstance(gate, dict)}
        != required_gates
        or any(gate.get("passed") is not True for gate in gates)
        or any(
            not SHA256_RE.fullmatch(str(gate.get("receipt_sha256", "")))
            for gate in gates
        )
    ):
        raise VerificationError("Agent/ART security gate failed")

    metrics = _load_json(documents, "aggregate-metrics.json")
    _verify_aggregate_metrics(metrics, sites)
    audit = _load_json(documents, "audit-chain.json")
    _verify_audit_chain(audit)
    release = _load_json(documents, "global-model-manifest.json")
    _verify_model_release(
        release,
        documents["model-release-public-key.pem"],
        job_id=str(job_id),
        contract_sha256=contract_sha,
        model_sha256=model_sha,
    )


def verify(package: Path, expected_fingerprint: str) -> dict[str, Any]:
    expected_fingerprint = _digest(expected_fingerprint, "expected signer fingerprint")
    documents, infos = _read_zip(package)
    manifest = _load_json(documents, "manifest.json")
    manifest_bytes = documents["manifest.json"]
    if _canonical_json(manifest) != manifest_bytes:
        raise VerificationError("manifest is not canonical JSON")
    if manifest.get("schema_version") != "rarelink-evidence-package-manifest-v2":
        raise VerificationError("unsupported evidence package schema")
    if (
        manifest.get("completed_site_count") != 3
        or manifest.get("quorum_required") != 3
        or manifest.get("patient_data_included") is not False
        or manifest.get("secret_included") is not False
        or manifest.get("private_key_included") is not False
    ):
        raise VerificationError("manifest completion or safety boundary failed")
    sites = manifest.get("expected_sites")
    if not isinstance(sites, list):
        raise VerificationError("expected site list is missing")
    expected_payloads = _expected_payload_files(sites)
    if set(documents) != expected_payloads | SUPPORT_FILES:
        raise VerificationError("package file set is incomplete or unexpected")
    executable = next(
        info for info in infos if info.filename == "verify-evidence-package"
    )
    if not executable.external_attr >> 16 & stat.S_IXUSR:
        raise VerificationError("embedded verifier is not executable")

    listed = manifest.get("files")
    if not isinstance(listed, list) or len(listed) != len(expected_payloads):
        raise VerificationError("manifest file inventory is invalid")
    listed_names: set[str] = set()
    for entry in listed:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size_bytes"}:
            raise VerificationError("manifest file entry is invalid")
        name = entry.get("path")
        if name not in expected_payloads or name in listed_names:
            raise VerificationError("manifest path is invalid")
        listed_names.add(name)
        content = documents[name]
        if entry.get("sha256") != _sha256(content) or entry.get("size_bytes") != len(content):
            raise VerificationError(f"digest failed for {name}")
        if name.endswith(".json"):
            _load_json(documents, name)
    try:
        report_text = documents["report.md"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise VerificationError("report.md is not UTF-8") from exc
    _reject_sensitive(report_text)
    if listed_names != expected_payloads:
        raise VerificationError("manifest does not cover every payload")

    try:
        package_key = serialization.load_pem_public_key(
            documents["signer-public-key.pem"]
        )
    except (TypeError, ValueError) as exc:
        raise VerificationError("package signer public key is invalid") from exc
    if not isinstance(package_key, Ed25519PublicKey):
        raise VerificationError("package signer is not Ed25519")
    actual_fingerprint = _fingerprint(package_key)
    if actual_fingerprint != expected_fingerprint:
        raise VerificationError("package signer does not match external trust anchor")
    signature = _load_json(documents, "signature.json")
    canonical = DOMAIN_SEPARATOR + manifest_bytes
    if (
        signature.get("schema_version")
        != "rarelink-evidence-package-signature-v2"
        or signature.get("algorithm") != "Ed25519"
        or signature.get("manifest_sha256") != _sha256(canonical)
        or signature.get("key_fingerprint_sha256") != actual_fingerprint
        or signature.get("private_key_exported") is not False
    ):
        raise VerificationError("package signature receipt failed")
    try:
        package_key.verify(_decode_signature(signature.get("signature")), canonical)
    except InvalidSignature as exc:
        raise VerificationError("package signature failed") from exc
    _verify_semantics(documents, manifest)
    return {
        "schema_version": "rarelink-evidence-package-verification-v2",
        "package_sha256": _sha256(package.read_bytes()),
        "manifest_sha256": _sha256(canonical),
        "key_fingerprint_sha256": actual_fingerprint,
        "study_id": manifest.get("study_id"),
        "job_id": manifest.get("job_id"),
        "completed_site_count": 3,
        "file_count": len(expected_payloads),
        "verified": True,
        "trust_anchor_matched": True,
        "model_release_signature_verified": True,
        "audit_chain_linkage_verified": True,
        "privacy_budget_verified": True,
        "security_gates_verified": True,
        "sensitive_content_scan_passed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a signed RareLink Research Evidence Package offline."
    )
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--expected-key-fingerprint", required=True)
    args = parser.parse_args()
    try:
        receipt = verify(args.package, args.expected_key_fingerprint)
    except (VerificationError, OSError) as exc:
        print(f"VERIFICATION FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
