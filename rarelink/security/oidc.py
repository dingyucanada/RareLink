"""Offline OIDC JWT validation for the physical federation control plane.

The adapter deliberately does not download discovery documents or JWKS. An API
boundary is responsible for obtaining, pinning, refreshing, and caching a
trusted JWKS before constructing :class:`OfflineOIDCAdapter`.
"""

from __future__ import annotations

import math
import re
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Final

import jwt

from rarelink.security.physical_rbac import PhysicalPrincipal, PhysicalRole

ALLOWED_ALGORITHMS: Final = frozenset({"RS256", "ES256"})
PRIVATE_JWK_FIELDS: Final = frozenset({"d", "p", "q", "dp", "dq", "qi", "oth"})
SITE_ID = re.compile(r"^[a-z][a-z0-9-]{2,62}$")


class OIDCValidationError(RuntimeError):
    """Safe authentication failure that never includes a token or raw claim."""

    status_code = 401
    error_code = "OIDC_TOKEN_INVALID"

    def __init__(self, category: str = "token_invalid") -> None:
        self.category = category
        super().__init__("OIDC identity validation failed")

    def public_detail(self) -> dict[str, str | int]:
        return {
            "code": self.error_code,
            "message": str(self),
            "status_code": self.status_code,
        }


class OIDCConfigurationError(ValueError):
    """Trusted OIDC policy or JWKS is unsafe or structurally invalid."""


@dataclass(frozen=True, slots=True)
class OIDCClaimsConfig:
    """Pinned validation policy and claim names for one trusted issuer."""

    issuer: str
    audience: str
    role_claim: str = "roles"
    organization_claim: str = "organization"
    site_claim: str = "site_ids"
    clock_skew_seconds: int = 30
    max_future_iat_seconds: int = 30

    def __post_init__(self) -> None:
        for value in (
            self.issuer,
            self.audience,
            self.role_claim,
            self.organization_claim,
            self.site_claim,
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("OIDC policy strings must be non-empty")
        if self.issuer != self.issuer.strip() or self.audience != self.audience.strip():
            raise ValueError("OIDC issuer and audience must not contain surrounding whitespace")
        claim_names = {self.role_claim, self.organization_claim, self.site_claim}
        if len(claim_names) != 3 or any(name != name.strip() for name in claim_names):
            raise ValueError("OIDC role, organization, and site claims must be distinct names")
        if not 0 <= self.clock_skew_seconds <= 300:
            raise ValueError("clock_skew_seconds must be between 0 and 300")
        if not 0 <= self.max_future_iat_seconds <= 300:
            raise ValueError("max_future_iat_seconds must be between 0 and 300")


def _fail(category: str) -> None:
    raise OIDCValidationError(category)


def _numeric_date(claims: dict[str, Any], name: str) -> float:
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("time_claim_invalid")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        _fail("time_claim_invalid")
    return numeric


def _validate_times(
    claims: dict[str, Any],
    config: OIDCClaimsConfig,
    now: float,
) -> None:
    expires_at = _numeric_date(claims, "exp")
    issued_at = _numeric_date(claims, "iat")
    if expires_at <= now - config.clock_skew_seconds:
        _fail("token_expired")
    if issued_at > now + config.max_future_iat_seconds:
        _fail("issued_in_future")
    if expires_at <= issued_at:
        _fail("time_claim_invalid")
    if "nbf" in claims:
        not_before = _numeric_date(claims, "nbf")
        if not_before > now + config.clock_skew_seconds:
            _fail("not_yet_valid")


def _claim_strings(
    value: Any,
    *,
    allow_empty_list: bool,
    category: str,
) -> tuple[str, ...]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        _fail(category)
    if not values and not allow_empty_list:
        _fail(category)
    if any(
        not isinstance(item, str)
        or not item
        or item != item.strip()
        or len(item) > 160
        for item in values
    ):
        _fail(category)
    if len(values) != len(set(values)):
        _fail(category)
    return tuple(values)


def _principal_from_claims(
    claims: dict[str, Any],
    config: OIDCClaimsConfig,
) -> PhysicalPrincipal:
    subject = claims.get("sub")
    if (
        not isinstance(subject, str)
        or not subject
        or subject != subject.strip()
        or len(subject) > 255
        or any(character.isspace() for character in subject)
    ):
        _fail("subject_invalid")

    raw_roles = _claim_strings(
        claims.get(config.role_claim),
        allow_empty_list=False,
        category="roles_invalid",
    )
    try:
        roles = frozenset(PhysicalRole(role) for role in raw_roles)
    except ValueError:
        _fail("roles_invalid")
    if not roles:
        _fail("roles_invalid")

    organization = claims.get(config.organization_claim)
    if (
        not isinstance(organization, str)
        or not organization
        or organization != organization.strip()
        or len(organization) > 160
    ):
        _fail("organization_invalid")

    raw_sites = _claim_strings(
        claims.get(config.site_claim),
        allow_empty_list=True,
        category="sites_invalid",
    )
    if any(not SITE_ID.fullmatch(site_id) for site_id in raw_sites):
        _fail("sites_invalid")

    try:
        return PhysicalPrincipal(
            subject_id=subject,
            roles=roles,
            organization=organization,
            site_ids=frozenset(raw_sites),
        )
    except (TypeError, ValueError):
        _fail("principal_invalid")


def _select_jwk(token: str, jwks: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        _fail("header_invalid")
    algorithm = header.get("alg")
    key_id = header.get("kid")
    if algorithm not in ALLOWED_ALGORITHMS:
        _fail("algorithm_rejected")
    if not isinstance(key_id, str) or not key_id or len(key_id) > 128:
        _fail("kid_invalid")
    keys = jwks.get("keys") if isinstance(jwks, dict) else None
    if not isinstance(keys, list) or len(keys) > 100:
        _fail("jwks_invalid")
    matching = [
        key
        for key in keys
        if isinstance(key, dict) and key.get("kid") == key_id
    ]
    if len(matching) != 1:
        _fail("kid_unknown")
    selected = matching[0]
    if PRIVATE_JWK_FIELDS.intersection(selected):
        _fail("private_jwk_rejected")
    expected_key_type = "RSA" if algorithm == "RS256" else "EC"
    if selected.get("kty") != expected_key_type:
        _fail("key_type_invalid")
    if selected.get("alg") not in {None, algorithm}:
        _fail("key_algorithm_invalid")
    if selected.get("use") not in {None, "sig"}:
        _fail("key_use_invalid")
    key_ops = selected.get("key_ops")
    if key_ops is not None and (
        not isinstance(key_ops, list)
        or "verify" not in key_ops
        or any(not isinstance(item, str) for item in key_ops)
    ):
        _fail("key_use_invalid")
    return algorithm, selected


class OfflineOIDCAdapter:
    """Validate a bearer JWT against an already trusted, in-memory JWKS."""

    def __init__(self, config: OIDCClaimsConfig, jwks: dict[str, Any]) -> None:
        if not isinstance(jwks, dict):
            raise TypeError("jwks must be an in-memory mapping")
        keys = jwks.get("keys")
        if (
            not isinstance(keys, list)
            or not keys
            or len(keys) > 100
            or any(not isinstance(key, dict) for key in keys)
        ):
            raise OIDCConfigurationError("Trusted JWKS must contain 1 to 100 public keys")
        if any(PRIVATE_JWK_FIELDS.intersection(key) for key in keys):
            raise OIDCConfigurationError("Trusted JWKS must not contain private key material")
        self.config = config
        self._jwks = deepcopy(jwks)

    def authenticate(self, token: str, *, now: float | None = None) -> PhysicalPrincipal:
        if (
            not isinstance(token, str)
            or not token
            or len(token) > 16_384
            or token != token.strip()
        ):
            _fail("token_invalid")
        algorithm, jwk = _select_jwk(token, self._jwks)
        try:
            verification_key = jwt.PyJWK.from_dict(jwk, algorithm=algorithm).key
            claims = jwt.decode(
                token,
                key=verification_key,
                algorithms=[algorithm],
                issuer=self.config.issuer,
                audience=self.config.audience,
                options={
                    "require": ["iss", "aud", "exp", "iat", "sub"],
                    "verify_signature": True,
                    "verify_iss": True,
                    "verify_aud": True,
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
        except jwt.PyJWTError:
            _fail("signature_or_registered_claim_invalid")
        if not isinstance(claims, dict):
            _fail("claims_invalid")
        _validate_times(claims, self.config, time.time() if now is None else now)
        return _principal_from_claims(claims, self.config)


def principal_from_oidc_jwt(
    token: str,
    *,
    trusted_jwks: dict[str, Any],
    config: OIDCClaimsConfig,
    now: float | None = None,
) -> PhysicalPrincipal:
    """Convenience function for adapters that do not retain an instance."""
    return OfflineOIDCAdapter(config, trusted_jwks).authenticate(token, now=now)
