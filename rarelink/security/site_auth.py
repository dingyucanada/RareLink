"""Interim authenticated heartbeat envelope for physical Site Agents.

The P0 control plane uses per-site HMAC secrets supplied by the runtime secret
store. This is intentionally isolated so P1 can replace it with hospital mTLS
identity without changing the heartbeat payload or registry service.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any


def canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def payload_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_payload(payload)).hexdigest()


def heartbeat_signature(
    site_id: str,
    timestamp: int,
    heartbeat_id: str,
    payload: dict[str, Any],
    secret: str,
) -> str:
    body_hash = payload_sha256(payload)
    message = f"{site_id}\n{timestamp}\n{heartbeat_id}\n{body_hash}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_heartbeat_signature(
    *,
    site_id: str,
    timestamp: int,
    heartbeat_id: str,
    payload: dict[str, Any],
    secret: str,
    signature: str,
    max_age_seconds: int,
    now: int | None = None,
) -> str:
    observed_now = int(time.time()) if now is None else now
    if abs(observed_now - timestamp) > max_age_seconds:
        raise ValueError("Heartbeat timestamp is outside the accepted replay window")
    expected = heartbeat_signature(site_id, timestamp, heartbeat_id, payload, secret)
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Heartbeat signature is invalid")
    return payload_sha256(payload)
