"""Ed25519 signatures for approved global-model release manifests.

Keys are loaded from coordinator-local files. The private key, path, and raw
model never enter the database or public receipt.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$")
DOMAIN_SEPARATOR = b"RareLink global model release v1\x00"


class ModelSigningError(ValueError):
    """A model manifest or signing-key operation failed closed."""


@dataclass(frozen=True)
class ModelReleaseManifest:
    job_id: str
    external_job_id: str
    contract_sha256: str
    model_sha256: str
    model_file_name: str
    approved_at: str

    def canonical_bytes(self) -> bytes:
        for label, value in (
            ("job_id", self.job_id),
            ("external_job_id", self.external_job_id),
        ):
            if not SAFE_ID_RE.fullmatch(value):
                raise ModelSigningError(f"{label} is invalid")
        for label, value in (
            ("contract_sha256", self.contract_sha256),
            ("model_sha256", self.model_sha256),
        ):
            if not SHA256_RE.fullmatch(value):
                raise ModelSigningError(f"{label} is invalid")
        file_name = Path(self.model_file_name)
        if (
            not self.model_file_name
            or file_name.name != self.model_file_name
            or self.model_file_name in {".", ".."}
        ):
            raise ModelSigningError("model_file_name must be a safe basename")
        try:
            approved_at = datetime.fromisoformat(self.approved_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ModelSigningError("approved_at must be ISO-8601") from error
        if approved_at.tzinfo is None:
            raise ModelSigningError("approved_at must include a timezone")
        normalized = {
            **asdict(self),
            "approved_at": approved_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "schema_version": "rarelink-model-release-manifest-v1",
        }
        return DOMAIN_SEPARATOR + json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()


def _regular_key_file(path: Path) -> Path:
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_file():
        raise ModelSigningError("Signing key must be a regular non-symlink file")
    return resolved


def _public_key_fingerprint(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw).hexdigest()


def sign_model_release(
    manifest: ModelReleaseManifest,
    *,
    private_key_path: Path,
) -> dict[str, object]:
    key_bytes = _regular_key_file(private_key_path).read_bytes()
    try:
        key = serialization.load_pem_private_key(key_bytes, password=None)
    except (TypeError, ValueError) as error:
        raise ModelSigningError("Unable to load model signing private key") from error
    if not isinstance(key, Ed25519PrivateKey):
        raise ModelSigningError("Model signing key must be Ed25519")
    canonical = manifest.canonical_bytes()
    signature = key.sign(canonical)
    return {
        "schema_version": "rarelink-model-release-signature-v1",
        "manifest_sha256": hashlib.sha256(canonical).hexdigest(),
        "key_fingerprint_sha256": _public_key_fingerprint(key.public_key()),
        "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii"),
        "algorithm": "Ed25519",
        "verified": True,
        "private_key_exported": False,
        "private_key_path_exported": False,
        "model_bytes_exported": False,
        "patient_data_exported": False,
    }


def verify_model_release(
    manifest: ModelReleaseManifest,
    *,
    signature: str,
    public_key_path: Path,
    expected_key_fingerprint_sha256: str,
) -> dict[str, object]:
    if not SHA256_RE.fullmatch(expected_key_fingerprint_sha256):
        raise ModelSigningError("Expected signing-key fingerprint is invalid")
    key_bytes = _regular_key_file(public_key_path).read_bytes()
    try:
        key = serialization.load_pem_public_key(key_bytes)
    except (TypeError, ValueError) as error:
        raise ModelSigningError("Unable to load model signing public key") from error
    if not isinstance(key, Ed25519PublicKey):
        raise ModelSigningError("Model verification key must be Ed25519")
    actual_fingerprint = _public_key_fingerprint(key)
    if actual_fingerprint != expected_key_fingerprint_sha256:
        raise ModelSigningError("Model signing-key fingerprint mismatch")
    try:
        padded = signature + "=" * (-len(signature) % 4)
        decoded_signature = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (UnicodeEncodeError, ValueError) as error:
        raise ModelSigningError("Model signature encoding is invalid") from error
    if len(decoded_signature) != 64:
        raise ModelSigningError("Model signature length is invalid")
    canonical = manifest.canonical_bytes()
    try:
        key.verify(decoded_signature, canonical)
    except InvalidSignature as error:
        raise ModelSigningError("Global model release signature is invalid") from error
    return {
        "schema_version": "rarelink-model-release-verification-v1",
        "manifest_sha256": hashlib.sha256(canonical).hexdigest(),
        "key_fingerprint_sha256": actual_fingerprint,
        "algorithm": "Ed25519",
        "verified": True,
        "model_bytes_exported": False,
        "patient_data_exported": False,
    }
