"""Controlled, offline-testable JWKS refresh and rotation lifecycle.

The default transport performs bounded direct HTTPS with certificate and
hostname verification and no redirects. Deployments may inject an approved
transport for hospital proxy, CA, DNS, and egress policy. Tokens, response
bodies, and transport exceptions are never logged or included in public errors.
"""

from __future__ import annotations

import json
import ssl
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from http.client import HTTPSConnection
from typing import Any, Protocol
from urllib.parse import urlsplit

import jwt

from rarelink.security.oidc import ALLOWED_ALGORITHMS

PRIVATE_JWK_FIELDS = frozenset({"d", "p", "q", "dp", "dq", "qi", "oth", "k"})


class JWKSRefreshError(RuntimeError):
    """Safe, non-secret refresh failure."""

    def __init__(self) -> None:
        super().__init__("Trusted OIDC signing keys are unavailable")


@dataclass(frozen=True, slots=True)
class JWKSHTTPResponse:
    """Bounded response returned by an injected transport."""

    status_code: int
    body: bytes
    content_type: str | None = None


class JWKSTransport(Protocol):
    def __call__(
        self,
        *,
        uri: str,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> JWKSHTTPResponse: ...


class _HTTPSResponse(Protocol):
    status: int

    def getheader(self, name: str, default: str | None = None) -> str | None: ...

    def read(self, amount: int | None = None) -> bytes: ...


class _HTTPSConnection(Protocol):
    def request(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None: ...

    def getresponse(self) -> _HTTPSResponse: ...

    def close(self) -> None: ...


class _HTTPSConnectionFactory(Protocol):
    def __call__(
        self,
        host: str,
        port: int,
        *,
        timeout: float,
        context: ssl.SSLContext,
    ) -> _HTTPSConnection: ...


class JWKSProviderSettings(Protocol):
    rarelink_oidc_issuer: str
    rarelink_oidc_jwks_uri: str
    rarelink_oidc_jwks_timeout_seconds: float
    rarelink_oidc_jwks_max_response_bytes: int
    rarelink_oidc_jwks_cache_ttl_seconds: int
    rarelink_oidc_jwks_old_key_grace_seconds: int

    @property
    def physical_oidc_jwks_allowed_uris(self) -> frozenset[str]: ...


def _https_origin(value: str) -> tuple[str, str, int]:
    parsed = urlsplit(value)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("OIDC issuer and JWKS URIs must be fixed HTTPS URLs")
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise ValueError("OIDC issuer and JWKS URIs contain an invalid port") from exc
    return "https", parsed.hostname.lower(), port


def _json_content_type(value: str | None) -> str:
    if not isinstance(value, str):
        raise JWKSRefreshError
    media_type = value.split(";", 1)[0].strip().lower()
    if media_type not in {"application/json", "application/jwk-set+json"}:
        raise JWKSRefreshError
    return media_type


class StrictHTTPSJWKSTransport:
    """Direct TLS transport with no redirects and bounded response reads.

    The default SSL context verifies the certificate chain and hostname.
    ``connection_factory`` exists solely to support offline tests and approved
    deployment adapters; production callers should normally keep the default.
    """

    def __init__(
        self,
        *,
        ssl_context: ssl.SSLContext | None = None,
        connection_factory: _HTTPSConnectionFactory = HTTPSConnection,
    ) -> None:
        if not callable(connection_factory):
            raise TypeError("HTTPS connection factory must be callable")
        self._ssl_context = ssl_context or ssl.create_default_context()
        if (
            self._ssl_context.verify_mode != ssl.CERT_REQUIRED
            or not self._ssl_context.check_hostname
        ):
            raise ValueError("JWKS HTTPS transport requires certificate verification")
        self._connection_factory = connection_factory

    def __call__(
        self,
        *,
        uri: str,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> JWKSHTTPResponse:
        try:
            _scheme, host, port = _https_origin(uri)
            if (
                isinstance(timeout_seconds, bool)
                or not 0.1 <= timeout_seconds <= 30
                or isinstance(max_response_bytes, bool)
                or not 1024 <= max_response_bytes <= 4 * 1024 * 1024
            ):
                raise JWKSRefreshError
            parsed = urlsplit(uri)
            request_target = parsed.path or "/"
            connection = self._connection_factory(
                host,
                port,
                timeout=timeout_seconds,
                context=self._ssl_context,
            )
        except Exception:
            raise JWKSRefreshError from None

        try:
            connection.request(
                "GET",
                request_target,
                headers={
                    "Accept": "application/jwk-set+json, application/json",
                    "Accept-Encoding": "identity",
                    "User-Agent": "RareLink-JWKS/1",
                },
            )
            response = connection.getresponse()
            if response.status != 200:
                raise JWKSRefreshError
            content_type = _json_content_type(response.getheader("Content-Type"))
            content_length = response.getheader("Content-Length")
            if content_length is not None:
                try:
                    declared_length = int(content_length)
                except (TypeError, ValueError):
                    raise JWKSRefreshError from None
                if declared_length < 0 or declared_length > max_response_bytes:
                    raise JWKSRefreshError
            body = response.read(max_response_bytes + 1)
            if not isinstance(body, bytes) or not body or len(body) > max_response_bytes:
                raise JWKSRefreshError
            return JWKSHTTPResponse(
                status_code=200,
                body=body,
                content_type=content_type,
            )
        except JWKSRefreshError:
            raise
        except Exception:
            raise JWKSRefreshError from None
        finally:
            with suppress(Exception):
                connection.close()


@dataclass(frozen=True, slots=True)
class JWKSRefreshPolicy:
    issuer: str
    jwks_uri: str
    allowed_jwks_uris: frozenset[str]
    timeout_seconds: float = 3.0
    max_response_bytes: int = 256 * 1024
    cache_ttl_seconds: int = 300
    old_key_grace_seconds: int = 120

    def __post_init__(self) -> None:
        if (
            not self.issuer
            or self.issuer != self.issuer.strip()
            or not self.jwks_uri
            or self.jwks_uri != self.jwks_uri.strip()
        ):
            raise ValueError("OIDC issuer and JWKS URI must be non-empty")
        if (
            not isinstance(self.allowed_jwks_uris, frozenset)
            or not self.allowed_jwks_uris
            or any(
                not isinstance(uri, str) or not uri or uri != uri.strip()
                for uri in self.allowed_jwks_uris
            )
        ):
            raise ValueError("JWKS URI allow-list must be a non-empty frozenset")
        issuer_origin = _https_origin(self.issuer)
        if self.jwks_uri not in self.allowed_jwks_uris:
            raise ValueError("JWKS URI must exactly match the configured allow-list")
        for uri in self.allowed_jwks_uris:
            if _https_origin(uri) != issuer_origin:
                raise ValueError("Every allowed JWKS URI must share the issuer HTTPS origin")
        if isinstance(self.timeout_seconds, bool) or not 0.1 <= self.timeout_seconds <= 30:
            raise ValueError("JWKS timeout must be between 0.1 and 30 seconds")
        if (
            isinstance(self.max_response_bytes, bool)
            or not 1024 <= self.max_response_bytes <= 4 * 1024 * 1024
        ):
            raise ValueError("JWKS response limit must be between 1 KiB and 4 MiB")
        if (
            isinstance(self.cache_ttl_seconds, bool)
            or not 1 <= self.cache_ttl_seconds <= 86_400
        ):
            raise ValueError("JWKS cache TTL must be between 1 second and 24 hours")
        if (
            isinstance(self.old_key_grace_seconds, bool)
            or not 0 <= self.old_key_grace_seconds <= 3_600
        ):
            raise ValueError("Old JWKS key grace must be between 0 and 3600 seconds")


def _public_jwks(body: bytes, max_response_bytes: int) -> dict[str, list[dict[str, Any]]]:
    if not body or len(body) > max_response_bytes:
        raise JWKSRefreshError
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise JWKSRefreshError from None
    if not isinstance(document, dict) or set(document) - {"keys"}:
        raise JWKSRefreshError
    keys = document.get("keys")
    if not isinstance(keys, list) or not keys or len(keys) > 100:
        raise JWKSRefreshError
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_key in keys:
        if not isinstance(raw_key, dict) or PRIVATE_JWK_FIELDS.intersection(raw_key):
            raise JWKSRefreshError
        kid = raw_key.get("kid")
        algorithm = raw_key.get("alg")
        key_type = raw_key.get("kty")
        if (
            not isinstance(kid, str)
            or not kid
            or kid != kid.strip()
            or len(kid) > 128
            or kid in seen
            or algorithm not in ALLOWED_ALGORITHMS
            or key_type != ("RSA" if algorithm == "RS256" else "EC")
            or raw_key.get("use") not in {None, "sig"}
        ):
            raise JWKSRefreshError
        key_ops = raw_key.get("key_ops")
        if key_ops is not None and (
            not isinstance(key_ops, list)
            or "verify" not in key_ops
            or any(not isinstance(item, str) for item in key_ops)
        ):
            raise JWKSRefreshError
        seen.add(kid)
        validated.append(dict(raw_key))
    return {"keys": validated}


def _token_kid(token: str) -> str:
    if (
        not isinstance(token, str)
        or not token
        or len(token) > 16_384
        or token != token.strip()
    ):
        raise JWKSRefreshError
    try:
        header = jwt.get_unverified_header(token)
    except (jwt.PyJWTError, TypeError, ValueError):
        raise JWKSRefreshError from None
    algorithm = header.get("alg")
    kid = header.get("kid")
    if (
        algorithm not in ALLOWED_ALGORITHMS
        or not isinstance(kid, str)
        or not kid
        or kid != kid.strip()
        or len(kid) > 128
    ):
        raise JWKSRefreshError
    return kid


class TrustedJWKSCache:
    """TTL cache with injected refresh and a short grace for removed known keys."""

    def __init__(
        self,
        policy: JWKSRefreshPolicy,
        transport: JWKSTransport,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not callable(transport) or not callable(clock):
            raise TypeError("JWKS transport and clock must be callable")
        self.policy = policy
        self._transport = transport
        self._clock = clock
        self._current: dict[str, dict[str, Any]] = {}
        self._retired: dict[str, tuple[dict[str, Any], float]] = {}
        self._expires_at = 0.0
        self._lock = threading.RLock()

    def preload(self) -> None:
        """Load trusted keys before accepting OIDC-protected traffic."""
        self.refresh()

    def refresh(self) -> None:
        """Replace current keys using only the injected, bounded transport."""
        with self._lock:
            try:
                response = self._transport(
                    uri=self.policy.jwks_uri,
                    timeout_seconds=self.policy.timeout_seconds,
                    max_response_bytes=self.policy.max_response_bytes,
                )
            except Exception:
                raise JWKSRefreshError from None
            if (
                not isinstance(response, JWKSHTTPResponse)
                or response.status_code != 200
                or not isinstance(response.body, bytes)
                or len(response.body) > self.policy.max_response_bytes
            ):
                raise JWKSRefreshError
            if response.content_type is not None:
                media_type = response.content_type.split(";", 1)[0].strip().lower()
                if media_type not in {"application/json", "application/jwk-set+json"}:
                    raise JWKSRefreshError
            document = _public_jwks(
                response.body,
                self.policy.max_response_bytes,
            )
            now = self._clock()
            incoming = {str(key["kid"]): key for key in document["keys"]}
            grace_deadline = now + self.policy.old_key_grace_seconds
            for kid, key in self._current.items():
                if kid not in incoming and self.policy.old_key_grace_seconds:
                    self._retired[kid] = (key, grace_deadline)
            self._retired = {
                kid: value
                for kid, value in self._retired.items()
                if value[1] > now and kid not in incoming
            }
            self._current = incoming
            self._expires_at = now + self.policy.cache_ttl_seconds

    def trusted_jwks_for_token(self, token: str) -> Mapping[str, Any]:
        """Return keys for one token, refreshing safely when required.

        An unknown kid triggers one controlled refresh. If refresh fails or the
        kid remains unknown, the token is rejected; stale/unknown material is
        never promoted to trusted.
        """
        kid = _token_kid(token)
        with self._lock:
            now = self._clock()
            if not self._current or now >= self._expires_at:
                self.refresh()
                now = self._clock()
            retired = self._retired.get(kid)
            known = kid in self._current or (retired is not None and retired[1] > now)
            if not known:
                self.refresh()
                now = self._clock()
                retired = self._retired.get(kid)
                known = kid in self._current or (
                    retired is not None and retired[1] > now
                )
            if not known:
                raise JWKSRefreshError
            keys = list(self._current.values())
            keys.extend(
                key
                for retired_kid, (key, deadline) in self._retired.items()
                if deadline > now and retired_kid not in self._current
            )
            return {"keys": [dict(key) for key in keys]}

    def safe_status(self) -> dict[str, int | bool]:
        """Return aggregate cache health without URI, kid, key, or token data."""
        with self._lock:
            now = self._clock()
            return {
                "loaded": bool(self._current),
                "fresh": bool(self._current) and now < self._expires_at,
                "current_key_count": len(self._current),
                "grace_key_count": sum(
                    1 for _key, deadline in self._retired.values() if deadline > now
                ),
                "contains_jwk_material": False,
                "contains_token": False,
            }


def build_preloaded_jwks_provider(
    settings: JWKSProviderSettings,
    *,
    transport: JWKSTransport | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> TrustedJWKSCache:
    """Build and preload a fail-closed provider from bounded application settings."""
    policy = JWKSRefreshPolicy(
        issuer=settings.rarelink_oidc_issuer,
        jwks_uri=settings.rarelink_oidc_jwks_uri,
        allowed_jwks_uris=settings.physical_oidc_jwks_allowed_uris,
        timeout_seconds=settings.rarelink_oidc_jwks_timeout_seconds,
        max_response_bytes=settings.rarelink_oidc_jwks_max_response_bytes,
        cache_ttl_seconds=settings.rarelink_oidc_jwks_cache_ttl_seconds,
        old_key_grace_seconds=settings.rarelink_oidc_jwks_old_key_grace_seconds,
    )
    provider = TrustedJWKSCache(
        policy,
        transport if transport is not None else StrictHTTPSJWKSTransport(),
        clock=clock,
    )
    provider.preload()
    return provider
