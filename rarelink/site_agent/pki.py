"""Offline public-certificate validation for one physical Site Agent.

Only public X.509 certificates, CA bundles, and CRLs are opened. Private keys
are never discovered, opened, hashed, logged, or returned.
"""

from __future__ import annotations

import hashlib
import stat
from datetime import UTC, datetime
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import (
    dsa,
    ec,
    ed448,
    ed25519,
    padding,
    rsa,
)
from cryptography.x509.oid import ExtensionOID, NameOID

from rarelink.site_agent.schemas import CheckResult


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def public_path_secure(path: Path, allowed_root: Path) -> bool:
    """Reject symlinks and writable components without opening file contents."""
    try:
        current_input = path
        while True:
            if current_input.is_symlink():
                return False
            if current_input == allowed_root:
                break
            if current_input.parent == current_input:
                return False
            current_input = current_input.parent
        resolved_path = path.resolve(strict=True)
        resolved_root = allowed_root.resolve(strict=True)
        if not resolved_path.is_relative_to(resolved_root):
            return False
        current = resolved_path
        while True:
            if current.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                return False
            if current == resolved_root:
                break
            current = current.parent
        return True
    except OSError:
        return False


def _certificate_times(certificate: x509.Certificate) -> tuple[datetime, datetime]:
    return certificate.not_valid_before_utc, certificate.not_valid_after_utc


def _verify_signed_object(
    signature: bytes,
    signed_bytes: bytes,
    hash_algorithm: object,
    public_key: object,
) -> None:
    if isinstance(public_key, rsa.RSAPublicKey):
        public_key.verify(signature, signed_bytes, padding.PKCS1v15(), hash_algorithm)
    elif isinstance(public_key, ec.EllipticCurvePublicKey):
        public_key.verify(signature, signed_bytes, ec.ECDSA(hash_algorithm))
    elif isinstance(public_key, dsa.DSAPublicKey):
        public_key.verify(signature, signed_bytes, hash_algorithm)
    elif isinstance(public_key, (ed25519.Ed25519PublicKey, ed448.Ed448PublicKey)):
        public_key.verify(signature, signed_bytes)
    else:
        raise InvalidSignature


def _verify_certificate_signature(
    certificate: x509.Certificate,
    issuer: x509.Certificate,
) -> None:
    _verify_signed_object(
        certificate.signature,
        certificate.tbs_certificate_bytes,
        certificate.signature_hash_algorithm,
        issuer.public_key(),
    )


def _load_ca_bundle(path: Path) -> tuple[list[x509.Certificate], str]:
    data = path.read_bytes()
    certificates = x509.load_pem_x509_certificates(data)
    if not certificates:
        raise ValueError("CA bundle contains no certificates")
    return certificates, _sha256(data)


def _validate_chain(
    leaf: x509.Certificate,
    trusted_certificates: list[x509.Certificate],
    observed_at: datetime,
) -> list[x509.Certificate]:
    chain: list[x509.Certificate] = []
    current = leaf
    seen: set[int] = set()
    for _ in range(10):
        candidates = [
            certificate
            for certificate in trusted_certificates
            if certificate.subject == current.issuer
        ]
        verified: list[x509.Certificate] = []
        for candidate in candidates:
            try:
                _verify_certificate_signature(current, candidate)
                verified.append(candidate)
            except InvalidSignature:
                continue
        if len(verified) != 1:
            raise ValueError("certificate chain is missing or ambiguous")
        issuer = verified[0]
        if issuer.serial_number in seen:
            raise ValueError("certificate chain contains a loop")
        seen.add(issuer.serial_number)
        valid_from, valid_until = _certificate_times(issuer)
        if not valid_from <= observed_at < valid_until:
            raise ValueError("certificate authority is outside its validity period")
        constraints = issuer.extensions.get_extension_for_oid(
            ExtensionOID.BASIC_CONSTRAINTS
        ).value
        if not constraints.ca:
            raise ValueError("certificate issuer is not a CA")
        chain.append(issuer)
        if issuer.subject == issuer.issuer:
            _verify_certificate_signature(issuer, issuer)
            return chain
        current = issuer
    raise ValueError("certificate chain exceeds the maximum depth")


def _identity_matches(certificate: x509.Certificate, expected: str) -> bool:
    try:
        names = certificate.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME
        ).value
        identities = {
            value.lower() for value in names.get_values_for_type(x509.DNSName)
        }
        identities.update(
            value.lower()
            for value in names.get_values_for_type(x509.UniformResourceIdentifier)
        )
        return expected.strip().lower() in identities
    except x509.ExtensionNotFound:
        identities = {
        value.lower()
        for attribute in certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if (value := attribute.value.strip())
        }
    return expected.strip().lower() in identities


def _validate_crl(
    path: Path,
    leaf: x509.Certificate,
    issuer: x509.Certificate,
    observed_at: datetime,
) -> tuple[str, str]:
    data = path.read_bytes()
    try:
        crl = x509.load_pem_x509_crl(data)
    except ValueError:
        crl = x509.load_der_x509_crl(data)
    if crl.issuer != issuer.subject:
        raise ValueError("CRL issuer does not match the leaf issuer")
    _verify_signed_object(
        crl.signature,
        crl.tbs_certlist_bytes,
        crl.signature_hash_algorithm,
        issuer.public_key(),
    )
    if crl.last_update_utc > observed_at:
        raise ValueError("CRL is not yet valid")
    if crl.next_update_utc is None or crl.next_update_utc <= observed_at:
        raise ValueError("CRL is stale")
    if crl.get_revoked_certificate_by_serial_number(leaf.serial_number) is not None:
        return "revoked", _sha256(data)
    return "not_revoked", _sha256(data)


def validate_public_certificate(
    *,
    certificate_path: Path | None,
    startup_kit: Path,
    expected_identity: str,
    minimum_valid_days: int,
    restrict_to_startup_kit: bool,
    ca_bundle: Path | None,
    require_chain: bool,
    crl_file: Path | None,
    require_crl: bool,
    now: datetime | None = None,
) -> CheckResult:
    safe_details = {
        "certificate_subject_exported": False,
        "certificate_content_exported": False,
        "private_key_content_read": False,
        "private_key_path_discovered": False,
        "local_path_exported": False,
        "ocsp_checked": False,
        "ocsp_boundary": "external_online_validation_not_performed",
    }
    if certificate_path is None:
        return CheckResult(ok=False, status="not_configured", details=safe_details)
    if certificate_path.is_symlink():
        return CheckResult(ok=False, status="symlink_rejected", details=safe_details)
    if not certificate_path.is_file():
        return CheckResult(ok=False, status="missing", details=safe_details)
    root = startup_kit if restrict_to_startup_kit else certificate_path.parent
    if not public_path_secure(certificate_path, root):
        return CheckResult(
            ok=False,
            status="insecure_path_permissions",
            details=safe_details,
        )
    try:
        certificate_data = certificate_path.read_bytes()
        certificate = x509.load_pem_x509_certificate(certificate_data)
        observed_at = now or datetime.now(UTC)
        valid_from, valid_until = _certificate_times(certificate)
        seconds_remaining = (valid_until - observed_at).total_seconds()
        if valid_from > observed_at:
            status = "not_yet_valid"
        elif seconds_remaining <= 0:
            status = "expired"
        elif seconds_remaining < minimum_valid_days * 86_400:
            status = "expiring_soon"
        else:
            status = "valid"
        details = {
            **safe_details,
            "valid_from": valid_from.isoformat(),
            "expires_at": valid_until.isoformat(),
            "minimum_valid_days": minimum_valid_days,
            "certificate_sha256": _sha256(certificate_data),
            "identity_matched": _identity_matches(certificate, expected_identity),
            "expected_identity_exported": False,
            "chain_status": "not_configured",
            "crl_status": "not_configured",
        }
        if status != "valid":
            return CheckResult(ok=False, status=status, details=details)
        if not details["identity_matched"]:
            return CheckResult(ok=False, status="identity_mismatch", details=details)

        chain: list[x509.Certificate] = []
        if ca_bundle is not None:
            if (
                ca_bundle.is_symlink()
                or not ca_bundle.is_file()
                or not public_path_secure(ca_bundle, ca_bundle.parent)
            ):
                return CheckResult(ok=False, status="ca_bundle_insecure", details=details)
            trusted, ca_digest = _load_ca_bundle(ca_bundle)
            chain = _validate_chain(certificate, trusted, observed_at)
            details.update(
                {
                    "chain_status": "verified",
                    "chain_length": len(chain),
                    "ca_bundle_sha256": ca_digest,
                }
            )
        elif require_chain:
            return CheckResult(ok=False, status="ca_bundle_missing", details=details)

        if crl_file is not None:
            if (
                crl_file.is_symlink()
                or not crl_file.is_file()
                or not public_path_secure(crl_file, crl_file.parent)
            ):
                return CheckResult(ok=False, status="crl_insecure", details=details)
            if not chain:
                return CheckResult(ok=False, status="crl_requires_chain", details=details)
            crl_status, crl_digest = _validate_crl(
                crl_file, certificate, chain[0], observed_at
            )
            details.update({"crl_status": crl_status, "crl_sha256": crl_digest})
            if crl_status == "revoked":
                return CheckResult(ok=False, status="certificate_revoked", details=details)
        elif require_crl:
            return CheckResult(ok=False, status="crl_missing", details=details)
        return CheckResult(ok=True, status="valid", details=details)
    except (
        InvalidSignature,
        OSError,
        TypeError,
        ValueError,
        x509.ExtensionNotFound,
    ):
        return CheckResult(ok=False, status="invalid", details=safe_details)
