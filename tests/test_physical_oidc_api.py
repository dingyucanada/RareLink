import json
import time
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from rarelink.api.main import app
from rarelink.config import Settings, get_settings

ISSUER = "https://identity.hospital.example"
AUDIENCE = "rarelink-physical-control"


def oidc_material() -> tuple[Any, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(
        private_key.public_key(),
        as_dict=True,
    )
    jwk.update({"kid": "hospital-key-1", "alg": "RS256", "use": "sig"})
    return private_key, jwk


def oidc_token(
    private_key: Any,
    *,
    subject: str,
    roles: list[str],
    site_ids: list[str] | None = None,
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": subject,
            "exp": now + 300,
            "iat": now - 5,
            "roles": roles,
            "organization": "hospital-research",
            "site_ids": site_ids or ["hospital-a"],
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "hospital-key-1"},
    )


def enable_physical_oidc(jwk: dict[str, Any]) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        rarelink_allow_llm=False,
        rarelink_physical_mode="physical",
        rarelink_physical_auth_mode="oidc",
        rarelink_audit_hmac_key="audit-key-for-physical-oidc-tests-0001",
        rarelink_oidc_issuer=ISSUER,
        rarelink_oidc_audience=AUDIENCE,
        rarelink_oidc_jwks_json=json.dumps({"keys": [jwk]}),
    )


def test_physical_oidc_identity_and_rbac_protect_operator_api(
    client: TestClient,
) -> None:
    private_key, jwk = oidc_material()
    enable_physical_oidc(jwk)
    research_lead = oidc_token(
        private_key,
        subject="lead-subject",
        roles=["research_lead"],
    )
    denied = client.post(
        "/api/physical/sites",
        headers={"Authorization": f"Bearer {research_lead}"},
        json={
            "site_id": "hospital-a",
            "display_name": "Hospital A Spark",
            "organization": "hospital_a",
        },
    )
    assert denied.status_code == 403

    site_admin = oidc_token(
        private_key,
        subject="site-admin-subject",
        roles=["site_admin"],
    )
    accepted = client.post(
        "/api/physical/sites",
        headers={"Authorization": f"Bearer {site_admin}"},
        json={
            "site_id": "hospital-a",
            "display_name": "Hospital A Spark",
            "organization": "hospital_a",
        },
    )
    assert accepted.status_code == 201
    assert "site-admin-subject" not in accepted.text
    assert site_admin not in accepted.text

    events = client.get(
        "/api/physical/events",
        headers={"Authorization": f"Bearer {site_admin}"},
    )
    assert events.status_code == 200
    assert events.json()["verified"] is True
    assert events.json()["events"][0]["actor"] == "site-admin-subject"
    assert site_admin not in events.text

    out_of_scope = client.post(
        "/api/physical/sites",
        headers={"Authorization": f"Bearer {site_admin}"},
        json={
            "site_id": "hospital-b",
            "display_name": "Hospital B Spark",
            "organization": "hospital_b",
        },
    )
    assert out_of_scope.status_code == 403
    assert "every target physical site" in out_of_scope.json()["detail"]
    assert "hospital-b" not in out_of_scope.json()["detail"]


def test_physical_oidc_rejects_legacy_and_invalid_bearer_credentials(
    client: TestClient,
) -> None:
    trusted_private, trusted_jwk = oidc_material()
    untrusted_private, _ = oidc_material()
    enable_physical_oidc(trusted_jwk)
    payload = {
        "site_id": "hospital-a",
        "display_name": "Hospital A Spark",
        "organization": "hospital_a",
    }

    legacy = client.post(
        "/api/physical/sites",
        headers={"X-RareLink-Operator-Token": "operator-secret"},
        json=payload,
    )
    assert legacy.status_code == 401

    invalid = oidc_token(
        untrusted_private,
        subject="site-admin-subject",
        roles=["site_admin"],
    )
    rejected = client.post(
        "/api/physical/sites",
        headers={"Authorization": f"Bearer {invalid}"},
        json=payload,
    )
    assert rejected.status_code == 401
    assert invalid not in rejected.text
    assert "site-admin-subject" not in rejected.text
    assert trusted_private is not None


def test_physical_mode_rejects_legacy_operator_auth_even_with_audit_key(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        rarelink_allow_llm=False,
        rarelink_physical_mode="physical",
        rarelink_physical_auth_mode="legacy-token",
        rarelink_audit_hmac_key="audit-key-for-physical-legacy-test-001",
        rarelink_physical_operator_token="operator-secret",
    )
    response = client.post(
        "/api/physical/sites",
        headers={"X-RareLink-Operator-Token": "operator-secret"},
        json={
            "site_id": "hospital-a",
            "display_name": "Hospital A Spark",
            "organization": "hospital_a",
        },
    )

    assert response.status_code == 503
    assert "requires OIDC" in response.json()["detail"]


def test_physical_oidc_missing_jwks_is_configuration_failure(
    client: TestClient,
) -> None:
    private_key, _ = oidc_material()
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        rarelink_allow_llm=False,
        rarelink_physical_mode="physical",
        rarelink_physical_auth_mode="oidc",
        rarelink_audit_hmac_key="audit-key-for-physical-missing-jwks-01",
        rarelink_oidc_issuer=ISSUER,
        rarelink_oidc_audience=AUDIENCE,
    )
    token = oidc_token(
        private_key,
        subject="site-admin-subject",
        roles=["site_admin"],
    )
    response = client.post(
        "/api/physical/sites",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "site_id": "hospital-a",
            "display_name": "Hospital A Spark",
            "organization": "hospital_a",
        },
    )

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]
    assert token not in response.text
