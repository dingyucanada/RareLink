from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from rarelink.security.model_signing import (
    ModelReleaseManifest,
    ModelSigningError,
    sign_model_release,
    verify_model_release,
)


@pytest.fixture
def signing_keys(tmp_path: Path) -> tuple[Path, Path]:
    private_key = Ed25519PrivateKey.generate()
    private_path = tmp_path / "release-private.pem"
    public_path = tmp_path / "release-public.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


def manifest() -> ModelReleaseManifest:
    return ModelReleaseManifest(
        job_id="job-001",
        external_job_id="flare-job-001",
        contract_sha256=hashlib.sha256(b"contract").hexdigest(),
        model_sha256=hashlib.sha256(b"model").hexdigest(),
        model_file_name="global-model.pt",
        approved_at=datetime.now(UTC).isoformat(),
    )


def test_sign_and_verify_release_without_exporting_key_or_model(
    signing_keys: tuple[Path, Path],
) -> None:
    private_path, public_path = signing_keys
    release = manifest()
    signed = sign_model_release(release, private_key_path=private_path)
    verified = verify_model_release(
        release,
        signature=str(signed["signature"]),
        public_key_path=public_path,
        expected_key_fingerprint_sha256=str(signed["key_fingerprint_sha256"]),
    )

    assert signed["verified"] is True
    assert signed["private_key_exported"] is False
    assert "private_path" not in signed
    assert verified["verified"] is True
    assert verified["manifest_sha256"] == signed["manifest_sha256"]


def test_signature_rejects_tampered_model_digest(
    signing_keys: tuple[Path, Path],
) -> None:
    private_path, public_path = signing_keys
    original = manifest()
    signed = sign_model_release(original, private_key_path=private_path)
    tampered = replace(original, model_sha256=hashlib.sha256(b"tampered").hexdigest())

    with pytest.raises(ModelSigningError, match="signature is invalid"):
        verify_model_release(
            tampered,
            signature=str(signed["signature"]),
            public_key_path=public_path,
            expected_key_fingerprint_sha256=str(signed["key_fingerprint_sha256"]),
        )


def test_verification_rejects_untrusted_key_fingerprint(
    signing_keys: tuple[Path, Path],
) -> None:
    private_path, public_path = signing_keys
    signed = sign_model_release(manifest(), private_key_path=private_path)

    with pytest.raises(ModelSigningError, match="fingerprint mismatch"):
        verify_model_release(
            manifest(),
            signature=str(signed["signature"]),
            public_key_path=public_path,
            expected_key_fingerprint_sha256="0" * 64,
        )


def test_signing_rejects_symlinked_private_key(
    signing_keys: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    private_path, _public_path = signing_keys
    link = tmp_path / "linked-private.pem"
    link.symlink_to(private_path)

    with pytest.raises(ModelSigningError, match="non-symlink"):
        sign_model_release(manifest(), private_key_path=link)
