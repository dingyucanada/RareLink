from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from rarelink.security.oidc import (
    OfflineOIDCAdapter,
    OIDCClaimsConfig,
    OIDCConfigurationError,
    OIDCValidationError,
)
from rarelink.security.physical_rbac import PhysicalRole

ISSUER = "https://identity.hospital.example"
AUDIENCE = "rarelink-physical-control"
NOW = int(time.time())


def rsa_material(kid: str = "rsa-key-1") -> tuple[Any, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return private_key, jwk


def ec_material(kid: str = "ec-key-1") -> tuple[Any, dict[str, Any]]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    jwk = jwt.algorithms.ECAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk.update({"kid": kid, "alg": "ES256", "use": "sig"})
    return private_key, jwk


def config() -> OIDCClaimsConfig:
    return OIDCClaimsConfig(
        issuer=ISSUER,
        audience=AUDIENCE,
        role_claim="rarelink_roles",
        organization_claim="hospital_org",
        site_claim="allowed_sites",
        clock_skew_seconds=5,
        max_future_iat_seconds=5,
    )


def claims(**updates: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "stable-user-123",
        "exp": NOW + 300,
        "iat": NOW - 5,
        "rarelink_roles": ["research_lead", "reviewer"],
        "hospital_org": "hospital-research",
        "allowed_sites": ["hospital-a", "hospital-b"],
    }
    payload.update(updates)
    return payload


def encode(
    payload: dict[str, Any],
    private_key: Any,
    *,
    algorithm: str = "RS256",
    kid: str = "rsa-key-1",
) -> str:
    return jwt.encode(payload, private_key, algorithm=algorithm, headers={"kid": kid})


@pytest.mark.parametrize(
    ("material", "algorithm", "kid"),
    [
        (rsa_material, "RS256", "rsa-key-1"),
        (ec_material, "ES256", "ec-key-1"),
    ],
)
def test_valid_rs256_and_es256_tokens_map_to_minimal_principal(
    material: Callable[[], tuple[Any, dict[str, Any]]],
    algorithm: str,
    kid: str,
) -> None:
    private_key, jwk = material()
    token = encode(claims(), private_key, algorithm=algorithm, kid=kid)

    principal = OfflineOIDCAdapter(config(), {"keys": [jwk]}).authenticate(token, now=NOW)

    assert principal.subject_id == "stable-user-123"
    assert principal.roles == frozenset(
        {PhysicalRole.RESEARCH_LEAD, PhysicalRole.REVIEWER}
    )
    assert principal.organization == "hospital-research"
    assert principal.site_ids == frozenset({"hospital-a", "hospital-b"})
    assert set(principal.safe_identity()) == {
        "subject_id",
        "roles",
        "organization",
        "site_ids",
        "access_token_exported",
        "refresh_token_exported",
        "raw_claims_exported",
    }


def test_single_role_and_site_strings_are_accepted() -> None:
    private_key, jwk = rsa_material()
    token = encode(
        claims(rarelink_roles="site_admin", allowed_sites="hospital-a"),
        private_key,
    )
    principal = OfflineOIDCAdapter(config(), {"keys": [jwk]}).authenticate(token, now=NOW)
    assert principal.roles == frozenset({PhysicalRole.SITE_ADMIN})
    assert principal.site_ids == frozenset({"hospital-a"})


@pytest.mark.parametrize(
    "payload",
    [
        claims(exp=NOW - 100),
        claims(iat=NOW + 100),
        claims(exp=NOW - 1, iat=NOW),
        claims(iss="https://attacker.example"),
        claims(aud="another-service"),
        {key: value for key, value in claims().items() if key != "sub"},
        {key: value for key, value in claims().items() if key != "exp"},
        {key: value for key, value in claims().items() if key != "iat"},
    ],
)
def test_registered_claim_failures_are_rejected(payload: dict[str, Any]) -> None:
    private_key, jwk = rsa_material()
    token = encode(payload, private_key)
    with pytest.raises(OIDCValidationError):
        OfflineOIDCAdapter(config(), {"keys": [jwk]}).authenticate(token, now=NOW)


@pytest.mark.parametrize(
    "bad_roles",
    [
        [],
        "",
        "unknown_role",
        ["research_lead", "unknown_role"],
        ["reviewer", "reviewer"],
        [" reviewer"],
        [1],
        {"role": "reviewer"},
    ],
)
def test_empty_unknown_or_malformed_roles_fail_closed(bad_roles: Any) -> None:
    private_key, jwk = rsa_material()
    token = encode(claims(rarelink_roles=bad_roles), private_key)
    with pytest.raises(OIDCValidationError) as captured:
        OfflineOIDCAdapter(config(), {"keys": [jwk]}).authenticate(token, now=NOW)
    assert captured.value.category == "roles_invalid"


@pytest.mark.parametrize(
    "updates",
    [
        {"hospital_org": ""},
        {"hospital_org": ["hospital-research"]},
        {"allowed_sites": [1]},
        {"allowed_sites": ["Hospital-A"]},
        {"allowed_sites": ["hospital-a", "hospital-a"]},
    ],
)
def test_malformed_organization_or_site_claims_are_rejected(updates: dict[str, Any]) -> None:
    private_key, jwk = rsa_material()
    token = encode(claims(**updates), private_key)
    with pytest.raises(OIDCValidationError):
        OfflineOIDCAdapter(config(), {"keys": [jwk]}).authenticate(token, now=NOW)


def test_none_hs256_unknown_kid_and_duplicate_kid_are_rejected() -> None:
    private_key, jwk = rsa_material()
    adapter = OfflineOIDCAdapter(config(), {"keys": [jwk]})
    none_token = jwt.encode(
        claims(),
        key="",
        algorithm="none",
        headers={"kid": "rsa-key-1"},
    )
    hs_token = jwt.encode(
        claims(),
        key="not-a-public-key-but-long-enough-for-hs256",
        algorithm="HS256",
        headers={"kid": "rsa-key-1"},
    )
    unknown_kid = encode(claims(), private_key, kid="unknown-key")

    for token in (none_token, hs_token, unknown_kid):
        with pytest.raises(OIDCValidationError):
            adapter.authenticate(token, now=NOW)
    with pytest.raises(OIDCValidationError):
        OfflineOIDCAdapter(config(), {"keys": [jwk, dict(jwk)]}).authenticate(
            encode(claims(), private_key),
            now=NOW,
        )


def test_wrong_signature_is_rejected() -> None:
    trusted_private, trusted_jwk = rsa_material()
    untrusted_private, _ = rsa_material()
    token = encode(claims(), untrusted_private)
    assert trusted_private is not None
    with pytest.raises(OIDCValidationError):
        OfflineOIDCAdapter(config(), {"keys": [trusted_jwk]}).authenticate(token, now=NOW)


def test_private_jwk_material_is_rejected() -> None:
    private_key, public_jwk = rsa_material()
    private_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key, as_dict=True)
    private_jwk.update(
        {
            "kid": public_jwk["kid"],
            "alg": "RS256",
            "use": "sig",
        }
    )
    with pytest.raises(OIDCConfigurationError, match="private"):
        OfflineOIDCAdapter(config(), {"keys": [private_jwk]})


def test_failures_never_echo_token_or_raw_claim_values() -> None:
    private_key, jwk = rsa_material()
    sentinel = "sensitive-subject-never-echo"
    token = encode(claims(sub=sentinel, rarelink_roles=[]), private_key)

    with pytest.raises(OIDCValidationError) as captured:
        OfflineOIDCAdapter(config(), {"keys": [jwk]}).authenticate(token, now=NOW)

    rendered = f"{captured.value} {captured.value.public_detail()}"
    assert token not in rendered
    assert sentinel not in rendered
    assert "rarelink_roles" not in rendered
