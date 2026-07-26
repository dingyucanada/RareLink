from __future__ import annotations

import base64
import json
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from rarelink.config import Settings
from rarelink.security.jwks import (
    JWKSHTTPResponse,
    JWKSRefreshError,
    JWKSRefreshPolicy,
    StrictHTTPSJWKSTransport,
    TrustedJWKSCache,
    build_preloaded_jwks_provider,
)
from rarelink.security.oidc import (
    OfflineOIDCAdapter,
    OIDCClaimsConfig,
    OIDCValidationError,
)
from rarelink.security.physical_rbac import PhysicalRole

ISSUER = "https://identity.hospital.example/tenant"
JWKS_URI = "https://identity.hospital.example/tenant/signing-keys"
AUDIENCE = "rarelink-physical-control"


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class QueueTransport:
    def __init__(self, *outcomes: JWKSHTTPResponse | Exception) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        *,
        uri: str,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> JWKSHTTPResponse:
        self.calls.append(
            {
                "uri": uri,
                "timeout_seconds": timeout_seconds,
                "max_response_bytes": max_response_bytes,
            }
        )
        if not self.outcomes:
            raise AssertionError("unexpected transport call")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeHTTPSResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = b'{"keys":[{"kid":"key-a"}]}',
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.body = body
        self.headers = headers or {
            "Content-Type": "application/jwk-set+json",
            "Content-Length": str(len(body)),
        }
        self.read_amounts: list[int | None] = []

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name, default)

    def read(self, amount: int | None = None) -> bytes:
        self.read_amounts.append(amount)
        return self.body if amount is None else self.body[:amount]


class FakeHTTPSConnection:
    def __init__(self, response: FakeHTTPSResponse) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []
        self.closed = False

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "body": body,
                "headers": headers,
            }
        )

    def getresponse(self) -> FakeHTTPSResponse:
        return self.response

    def close(self) -> None:
        self.closed = True


class FakeHTTPSConnectionFactory:
    def __init__(
        self,
        response: FakeHTTPSResponse | None = None,
        *,
        failure: Exception | None = None,
    ) -> None:
        self.connection = FakeHTTPSConnection(response or FakeHTTPSResponse())
        self.failure = failure
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        host: str,
        port: int,
        *,
        timeout: float,
        context: Any,
    ) -> FakeHTTPSConnection:
        self.calls.append(
            {
                "host": host,
                "port": port,
                "timeout": timeout,
                "context": context,
            }
        )
        if self.failure is not None:
            raise self.failure
        return self.connection


def policy(
    *,
    cache_ttl_seconds: int = 30,
    old_key_grace_seconds: int = 5,
) -> JWKSRefreshPolicy:
    return JWKSRefreshPolicy(
        issuer=ISSUER,
        jwks_uri=JWKS_URI,
        allowed_jwks_uris=frozenset({JWKS_URI}),
        timeout_seconds=2.5,
        max_response_bytes=64 * 1024,
        cache_ttl_seconds=cache_ttl_seconds,
        old_key_grace_seconds=old_key_grace_seconds,
    )


def public_key(kid: str) -> dict[str, Any]:
    return {
        "kid": kid,
        "alg": "RS256",
        "kty": "RSA",
        "use": "sig",
        "key_ops": ["verify"],
        "n": "AQ",
        "e": "AQAB",
    }


def response(*keys: dict[str, Any]) -> JWKSHTTPResponse:
    return JWKSHTTPResponse(
        status_code=200,
        body=json.dumps({"keys": list(keys)}).encode(),
        content_type="application/jwk-set+json; charset=utf-8",
    )


def token_header(kid: str, algorithm: str = "RS256") -> str:
    def encode_part(value: dict[str, Any]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{encode_part({'alg': algorithm, 'kid': kid})}.{encode_part({})}.c2lnbmF0dXJl"


@pytest.mark.parametrize(
    ("issuer", "jwks_uri", "allowed"),
    [
        (
            ISSUER,
            "http://identity.hospital.example/keys",
            frozenset({"http://identity.hospital.example/keys"}),
        ),
        (
            ISSUER,
            "https://attacker.example/keys",
            frozenset({"https://attacker.example/keys"}),
        ),
        (
            ISSUER,
            JWKS_URI,
            frozenset({"https://identity.hospital.example/other-keys"}),
        ),
        (
            ISSUER,
            f"{JWKS_URI}?tenant=other",
            frozenset({f"{JWKS_URI}?tenant=other"}),
        ),
    ],
)
def test_policy_requires_fixed_https_exact_allowlist_and_issuer_origin(
    issuer: str,
    jwks_uri: str,
    allowed: frozenset[str],
) -> None:
    with pytest.raises(ValueError):
        JWKSRefreshPolicy(
            issuer=issuer,
            jwks_uri=jwks_uri,
            allowed_jwks_uris=allowed,
        )


def test_default_https_transport_verifies_tls_and_reads_only_one_bounded_response() -> None:
    body = b'{"keys":[{"kid":"key-a"}]}'
    fake_response = FakeHTTPSResponse(body=body)
    factory = FakeHTTPSConnectionFactory(fake_response)
    transport = StrictHTTPSJWKSTransport(connection_factory=factory)

    result = transport(
        uri=JWKS_URI,
        timeout_seconds=2.5,
        max_response_bytes=1024,
    )

    assert result == JWKSHTTPResponse(
        status_code=200,
        body=body,
        content_type="application/jwk-set+json",
    )
    assert len(factory.calls) == 1
    assert factory.calls[0]["host"] == "identity.hospital.example"
    assert factory.calls[0]["port"] == 443
    assert factory.calls[0]["timeout"] == 2.5
    assert factory.calls[0]["context"].check_hostname is True
    assert factory.connection.requests == [
        {
            "method": "GET",
            "url": "/tenant/signing-keys",
            "body": None,
            "headers": {
                "Accept": "application/jwk-set+json, application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "RareLink-JWKS/1",
            },
        }
    ]
    assert fake_response.read_amounts == [1025]
    assert factory.connection.closed is True


def test_default_https_transport_rejects_redirect_without_following_it() -> None:
    redirect = FakeHTTPSResponse(
        status=302,
        body=b"",
        headers={
            "Content-Type": "text/html",
            "Location": "https://attacker.example/keys",
        },
    )
    factory = FakeHTTPSConnectionFactory(redirect)
    transport = StrictHTTPSJWKSTransport(connection_factory=factory)

    with pytest.raises(JWKSRefreshError):
        transport(
            uri=JWKS_URI,
            timeout_seconds=2.5,
            max_response_bytes=1024,
        )

    assert len(factory.calls) == 1
    assert len(factory.connection.requests) == 1
    assert redirect.read_amounts == []
    assert factory.connection.closed is True


@pytest.mark.parametrize(
    "fake_response",
    [
        FakeHTTPSResponse(status=503),
        FakeHTTPSResponse(headers={"Content-Length": "2"}),
        FakeHTTPSResponse(
            headers={
                "Content-Type": "text/html",
                "Content-Length": "2",
            }
        ),
        FakeHTTPSResponse(
            headers={
                "Content-Type": "application/json",
                "Content-Length": "not-an-integer",
            }
        ),
        FakeHTTPSResponse(
            body=b"x" * 1025,
            headers={
                "Content-Type": "application/json",
                "Content-Length": "1025",
            },
        ),
        FakeHTTPSResponse(
            body=b"x" * 1025,
            headers={"Content-Type": "application/json"},
        ),
        FakeHTTPSResponse(
            body=b"",
            headers={
                "Content-Type": "application/json",
                "Content-Length": "0",
            },
        ),
    ],
)
def test_default_https_transport_rejects_bad_status_type_length_or_body(
    fake_response: FakeHTTPSResponse,
) -> None:
    transport = StrictHTTPSJWKSTransport(
        connection_factory=FakeHTTPSConnectionFactory(fake_response)
    )

    with pytest.raises(JWKSRefreshError):
        transport(
            uri=JWKS_URI,
            timeout_seconds=2.5,
            max_response_bytes=1024,
        )


def test_default_https_transport_hides_connection_exception_and_uri_details() -> None:
    sentinel = "network-secret-must-not-escape"
    transport = StrictHTTPSJWKSTransport(
        connection_factory=FakeHTTPSConnectionFactory(
            failure=RuntimeError(sentinel)
        )
    )

    with pytest.raises(JWKSRefreshError) as captured:
        transport(
            uri=JWKS_URI,
            timeout_seconds=2.5,
            max_response_bytes=1024,
        )

    assert str(captured.value) == "Trusted OIDC signing keys are unavailable"
    assert sentinel not in str(captured.value)
    assert JWKS_URI not in str(captured.value)


def test_startup_preload_and_ttl_refresh_use_only_injected_bounded_transport() -> None:
    clock = FakeClock()
    transport = QueueTransport(response(public_key("key-a")), response(public_key("key-a")))
    cache = TrustedJWKSCache(policy(), transport, clock=clock)

    cache.preload()

    assert transport.calls == [
        {
            "uri": JWKS_URI,
            "timeout_seconds": 2.5,
            "max_response_bytes": 64 * 1024,
        }
    ]
    assert cache.safe_status() == {
        "loaded": True,
        "fresh": True,
        "current_key_count": 1,
        "grace_key_count": 0,
        "contains_jwk_material": False,
        "contains_token": False,
    }

    cache.trusted_jwks_for_token(token_header("key-a"))
    assert len(transport.calls) == 1

    clock.advance(31)
    cache.trusted_jwks_for_token(token_header("key-a"))
    assert len(transport.calls) == 2


def test_settings_builder_constructs_and_preloads_provider_before_returning() -> None:
    settings = Settings(
        _env_file=None,
        rarelink_oidc_issuer=ISSUER,
        rarelink_oidc_jwks_uri=JWKS_URI,
        rarelink_oidc_jwks_allowed_uris_json=json.dumps([JWKS_URI]),
        rarelink_oidc_jwks_timeout_seconds=2.5,
        rarelink_oidc_jwks_max_response_bytes=64 * 1024,
        rarelink_oidc_jwks_cache_ttl_seconds=30,
        rarelink_oidc_jwks_old_key_grace_seconds=5,
    )
    transport = QueueTransport(response(public_key("key-a")))

    provider = build_preloaded_jwks_provider(
        settings,
        transport=transport,
        clock=FakeClock(),
    )

    assert provider.safe_status()["loaded"] is True
    assert provider.safe_status()["fresh"] is True
    assert provider.policy == policy()
    assert len(transport.calls) == 1


def test_settings_builder_does_not_return_provider_when_preload_fails() -> None:
    settings = Settings(
        _env_file=None,
        rarelink_oidc_issuer=ISSUER,
        rarelink_oidc_jwks_uri=JWKS_URI,
        rarelink_oidc_jwks_allowed_uris_json=json.dumps([JWKS_URI]),
    )

    with pytest.raises(JWKSRefreshError):
        build_preloaded_jwks_provider(
            settings,
            transport=QueueTransport(TimeoutError("must-not-escape")),
            clock=FakeClock(),
        )


def test_successful_rotation_keeps_only_previously_known_key_for_short_grace() -> None:
    clock = FakeClock()
    old_key = public_key("key-old")
    new_key = public_key("key-new")
    transport = QueueTransport(response(old_key), response(new_key), response(new_key))
    cache = TrustedJWKSCache(policy(old_key_grace_seconds=5), transport, clock=clock)
    cache.preload()

    cache.refresh()
    grace_jwks = cache.trusted_jwks_for_token(token_header("key-old"))

    assert {key["kid"] for key in grace_jwks["keys"]} == {"key-old", "key-new"}
    assert cache.safe_status()["grace_key_count"] == 1

    clock.advance(6)
    with pytest.raises(JWKSRefreshError):
        cache.trusted_jwks_for_token(token_header("key-old"))
    assert cache.safe_status()["grace_key_count"] == 0


def test_unknown_key_refresh_failure_is_fail_closed_and_does_not_echo_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "transport-secret-that-must-not-escape"
    unknown_token = token_header("unknown-sensitive-kid")
    transport = QueueTransport(
        response(public_key("known-key")),
        RuntimeError(secret),
    )
    cache = TrustedJWKSCache(policy(), transport, clock=FakeClock())
    cache.preload()

    with pytest.raises(JWKSRefreshError) as captured:
        cache.trusted_jwks_for_token(unknown_token)

    rendered = str(captured.value)
    assert rendered == "Trusted OIDC signing keys are unavailable"
    assert secret not in rendered
    assert unknown_token not in rendered
    assert "unknown-sensitive-kid" not in rendered
    assert not caplog.records


def test_expired_cache_rejects_even_a_previously_known_key_when_refresh_fails() -> None:
    clock = FakeClock()
    transport = QueueTransport(
        response(public_key("known-key")),
        TimeoutError("upstream timeout"),
    )
    cache = TrustedJWKSCache(
        policy(cache_ttl_seconds=10),
        transport,
        clock=clock,
    )
    cache.preload()
    clock.advance(11)

    with pytest.raises(JWKSRefreshError):
        cache.trusted_jwks_for_token(token_header("known-key"))


@pytest.mark.parametrize(
    "bad_response",
    [
        JWKSHTTPResponse(503, b"{}", "application/json"),
        JWKSHTTPResponse(200, b"x" * (64 * 1024 + 1), "application/json"),
        JWKSHTTPResponse(200, b'{"keys":[]}', "text/html"),
        response(public_key("duplicate"), public_key("duplicate")),
        response({**public_key("private"), "d": "secret-private-material"}),
        response({**public_key("symmetric"), "k": "secret-symmetric-material"}),
    ],
)
def test_malformed_oversized_private_or_unexpected_responses_are_rejected(
    bad_response: JWKSHTTPResponse,
) -> None:
    cache = TrustedJWKSCache(
        policy(),
        QueueTransport(bad_response),
        clock=FakeClock(),
    )

    with pytest.raises(JWKSRefreshError):
        cache.preload()


def rsa_material(kid: str) -> tuple[Any, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return private_key, jwk


def test_offline_oidc_adapter_accepts_preloaded_provider_and_rotated_public_key() -> None:
    now = int(time.time())
    private_key, jwk = rsa_material("active-signing-key")
    signed_token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "research-lead-1",
            "exp": now + 300,
            "iat": now - 5,
            "roles": ["research_lead"],
            "organization": "hospital-research",
            "site_ids": ["hospital-a"],
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "active-signing-key"},
    )
    transport = QueueTransport(response(jwk))
    cache = TrustedJWKSCache(policy(), transport, clock=FakeClock())
    cache.preload()
    adapter = OfflineOIDCAdapter(
        OIDCClaimsConfig(issuer=ISSUER, audience=AUDIENCE),
        cache,
    )

    principal = adapter.authenticate(signed_token, now=now)

    assert principal.subject_id == "research-lead-1"
    assert principal.roles == frozenset({PhysicalRole.RESEARCH_LEAD})
    assert principal.site_ids == frozenset({"hospital-a"})
    assert len(transport.calls) == 1


def test_provider_failure_is_exposed_only_as_safe_oidc_category() -> None:
    class FailedProvider:
        def trusted_jwks_for_token(self, token: str) -> dict[str, Any]:
            raise RuntimeError(f"must-not-echo:{token}")

    adapter = OfflineOIDCAdapter(
        OIDCClaimsConfig(issuer=ISSUER, audience=AUDIENCE),
        FailedProvider(),
    )
    sensitive_token = token_header("sensitive-kid")

    with pytest.raises(OIDCValidationError) as captured:
        adapter.authenticate(sensitive_token)

    assert captured.value.category == "trusted_keys_unavailable"
    assert sensitive_token not in str(captured.value)
