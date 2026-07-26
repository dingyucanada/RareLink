"""Forward one Site Agent's signed, patient-free heartbeat to the coordinator."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rarelink.site_agent.forwarder import BackoffPolicy, HeartbeatOutbox


@dataclass(frozen=True)
class ForwardRequest:
    url: str
    body: bytes
    headers: dict[str, str]


def build_forward_request(
    envelope: dict[str, Any],
    coordinator_url: str,
    demo_token: str = "",
) -> ForwardRequest:
    required = {
        "site_id",
        "timestamp",
        "heartbeat_id",
        "payload",
        "payload_sha256",
        "signature",
    }
    if not required.issubset(envelope):
        raise ValueError("Site Agent heartbeat envelope is incomplete")
    payload = envelope["payload"]
    if not isinstance(payload, dict) or payload.get("contains_patient_data") is not False:
        raise ValueError("Site heartbeat payload must explicitly exclude patient data")
    if payload.get("heartbeat_id") != envelope["heartbeat_id"]:
        raise ValueError("Heartbeat envelope and payload IDs do not match")
    site_id = str(envelope["site_id"])
    url = (
        coordinator_url.rstrip("/")
        + f"/api/physical/sites/{urllib.parse.quote(site_id, safe='')}/heartbeat"
    )
    headers = {
        "Content-Type": "application/json",
        "X-RareLink-Site-Timestamp": str(envelope["timestamp"]),
        "X-RareLink-Site-Signature": str(envelope["signature"]),
    }
    if demo_token:
        headers["X-RareLink-Demo-Token"] = demo_token
    return ForwardRequest(
        url=url,
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
    )


def fetch_envelope(agent_url: str, api_token: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        agent_url.rstrip("/") + "/v1/site/heartbeat",
        headers={"Authorization": f"Bearer {api_token}"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = json.loads(response.read())
    if not isinstance(payload, dict):
        raise ValueError("Site Agent heartbeat response must be a JSON object")
    return payload


def forward_once(
    *,
    agent_url: str,
    coordinator_url: str,
    api_token: str,
    demo_token: str,
    timeout: float,
) -> dict[str, Any]:
    envelope = fetch_envelope(agent_url, api_token, timeout)
    prepared = build_forward_request(envelope, coordinator_url, demo_token)
    request = urllib.request.Request(
        prepared.url,
        data=prepared.body,
        method="POST",
        headers=prepared.headers,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        result = json.loads(response.read())
    if not isinstance(result, dict):
        raise ValueError("Coordinator heartbeat response must be a JSON object")
    return {
        "site_id": result.get("site_id"),
        "status": result.get("status"),
        "last_heartbeat_at": result.get("last_heartbeat_at"),
        "contains_patient_data": False,
        "agent_api_token_exported": False,
        "demo_token_exported": False,
    }


def send_envelope(
    *,
    envelope: dict[str, Any],
    coordinator_url: str,
    demo_token: str,
    timeout: float,
) -> dict[str, Any]:
    prepared = build_forward_request(envelope, coordinator_url, demo_token)
    request = urllib.request.Request(
        prepared.url,
        data=prepared.body,
        method="POST",
        headers=prepared.headers,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        result = json.loads(response.read())
    if not isinstance(result, dict):
        raise ValueError("Coordinator heartbeat response must be a JSON object")
    return result


def reliable_forward_once(
    *,
    outbox: HeartbeatOutbox,
    agent_url: str,
    coordinator_url: str,
    api_token: str,
    demo_token: str,
    timeout: float,
    now: float,
) -> dict[str, Any]:
    state = outbox.state()
    if state.next_attempt_at > now:
        return {
            "forwarded": False,
            "deferred": True,
            "retry_after_seconds": round(state.next_attempt_at - now, 3),
            "contains_patient_data": False,
            "secret_exported": False,
        }
    envelope = state.pending_envelope
    if envelope is not None:
        timestamp = envelope.get("timestamp")
        if (
            not isinstance(timestamp, (int, float))
            or now - float(timestamp) >= outbox.policy.maximum_envelope_age_seconds
        ):
            outbox.discard_stale(str(envelope.get("heartbeat_id", "")))
            envelope = None
    try:
        if envelope is None:
            envelope = fetch_envelope(agent_url, api_token, timeout)
            envelope = outbox.enqueue(envelope)
            if envelope is None:
                return {
                    "forwarded": False,
                    "duplicate_suppressed": True,
                    "contains_patient_data": False,
                    "secret_exported": False,
                }
        result = send_envelope(
            envelope=envelope,
            coordinator_url=coordinator_url,
            demo_token=demo_token,
            timeout=timeout,
        )
        outbox.record_accepted(str(envelope["heartbeat_id"]))
        return {
            "forwarded": True,
            "site_id": result.get("site_id"),
            "status": result.get("status"),
            "contains_patient_data": False,
            "secret_exported": False,
        }
    except urllib.error.HTTPError as exc:
        if exc.code == 409 and envelope is not None:
            outbox.record_accepted(str(envelope["heartbeat_id"]))
            return {
                "forwarded": True,
                "duplicate_already_accepted": True,
                "contains_patient_data": False,
                "secret_exported": False,
            }
        delay = outbox.record_failure(now)
        return {
            "forwarded": False,
            "error_type": type(exc).__name__,
            "retry_after_seconds": delay,
            "contains_patient_data": False,
            "secret_exported": False,
        }
    except (OSError, ValueError, urllib.error.URLError) as exc:
        delay = outbox.record_failure(now)
        return {
            "forwarded": False,
            "error_type": type(exc).__name__,
            "retry_after_seconds": delay,
            "contains_patient_data": False,
            "secret_exported": False,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Forward signed RareLink Site Agent heartbeats")
    parser.add_argument("--agent-url", default="http://127.0.0.1:9100")
    parser.add_argument("--coordinator-url", required=True)
    parser.add_argument("--interval", type=float, default=0)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument(
        "--state-database",
        type=Path,
        default=Path("/var/lib/rarelink/site-agent/heartbeat-forwarder.sqlite3"),
    )
    parser.add_argument("--maximum-backoff", type=float, default=300)
    parser.add_argument("--maximum-envelope-age", type=float, default=240)
    args = parser.parse_args()
    api_token = os.environ.get("RARELINK_SITE_AGENT_API_TOKEN", "")
    if not api_token:
        raise RuntimeError("RARELINK_SITE_AGENT_API_TOKEN is required")
    demo_token = os.environ.get("RARELINK_DEMO_ACCESS_TOKEN", "")
    outbox = HeartbeatOutbox(
        args.state_database,
        BackoffPolicy(
            base_seconds=max(5, args.interval or 5),
            maximum_seconds=max(args.maximum_backoff, max(5, args.interval or 5)),
            maximum_envelope_age_seconds=args.maximum_envelope_age,
        ),
    )

    while True:
        result = reliable_forward_once(
            outbox=outbox,
            agent_url=args.agent_url,
            coordinator_url=args.coordinator_url,
            api_token=api_token,
            demo_token=demo_token,
            timeout=args.timeout,
            now=time.time(),
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if not args.interval:
            break
        time.sleep(max(5, float(result.get("retry_after_seconds", args.interval))))


if __name__ == "__main__":
    main()
