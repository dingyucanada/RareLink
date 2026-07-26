"""Strict parsers for coordinator-owned NVFLARE registry and result artifacts."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any

from rarelink.services.physical_controller import (
    CLIENT_OFFLINE_STATES,
    CLIENT_ONLINE_STATES,
    JobValidationError,
)


def _cli_data(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise JobValidationError("NVFLARE JSON response must be an object")
    if "data" in payload:
        if payload.get("status") not in (None, "ok", "OK", "success", "SUCCESS"):
            raise JobValidationError("NVFLARE JSON response did not report success")
        data = payload["data"]
        if not isinstance(data, dict):
            raise JobValidationError("NVFLARE JSON response data must be an object")
        return data
    return payload


@dataclass(frozen=True)
class ClientRegistryEntry:
    site_id: str
    state: str
    connected: bool

    def public_receipt(self) -> dict[str, Any]:
        return {
            "site_id": self.site_id,
            "state": self.state,
            "connected": self.connected,
        }


def _registry_items(data: dict[str, Any]) -> list[Any]:
    for key in ("clients", "client_statuses", "results"):
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [
                (
                    {"site_id": site_id, **status}
                    if isinstance(status, dict)
                    else {"site_id": site_id, "status": status}
                )
                for site_id, status in value.items()
            ]
    if isinstance(data.get("client"), list):
        return data["client"]
    raise JobValidationError("NVFLARE client registry is missing a client list")


def parse_client_registry(
    payload: Any,
    expected_sites: tuple[str, str, str],
) -> dict[str, Any]:
    """Return an allow-listed three-site registry without relaying tokens."""
    if len(expected_sites) != 3 or len(set(expected_sites)) != 3:
        raise JobValidationError("Client registry requires three distinct expected sites")
    items = _registry_items(_cli_data(payload))
    parsed: dict[str, ClientRegistryEntry] = {}
    for item in items:
        if not isinstance(item, dict):
            raise JobValidationError("NVFLARE client registry entries must be objects")
        identities = [
            item[key]
            for key in ("site_id", "name", "site", "client", "client_name")
            if isinstance(item.get(key), str) and item[key]
        ]
        identities = list(dict.fromkeys(identities))
        if len(identities) != 1:
            raise JobValidationError("NVFLARE client identity is missing or ambiguous")
        site_id = identities[0]
        if site_id not in expected_sites:
            raise JobValidationError("NVFLARE client registry contains an unexpected site")
        if site_id in parsed:
            raise JobValidationError("NVFLARE client registry contains a duplicate site")
        raw_state = item.get("status", item.get("state"))
        if isinstance(raw_state, bool):
            state = "CONNECTED" if raw_state else "DISCONNECTED"
        elif isinstance(raw_state, str):
            state = raw_state.strip().upper().replace("-", "_").replace(" ", "_")
        else:
            raise JobValidationError("NVFLARE client registry status is invalid")
        if state in CLIENT_ONLINE_STATES:
            connected = True
        elif state in CLIENT_OFFLINE_STATES:
            connected = False
        else:
            raise JobValidationError("NVFLARE client registry status is unknown")
        parsed[site_id] = ClientRegistryEntry(site_id, state, connected)

    entries = [
        parsed.get(site_id, ClientRegistryEntry(site_id, "NOT_REPORTED", False))
        for site_id in expected_sites
    ]
    connected_sites = [entry.site_id for entry in entries if entry.connected]
    return {
        "schema_version": "rarelink-nvflare-client-registry-v1",
        "clients": [entry.public_receipt() for entry in entries],
        "connected_sites": connected_sites,
        "missing_sites": [site_id for site_id in expected_sites if site_id not in connected_sites],
        "all_expected_connected": len(connected_sites) == 3,
        "expected_client_count": 3,
        "token_exported": False,
        "secret_exported": False,
        "patient_data_exported": False,
    }


def _finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise JobValidationError(f"Aggregate metric {field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise JobValidationError(f"Aggregate metric {field_name} must be finite")
    return result


def parse_aggregate_metrics(
    payload: Any,
    expected_sites: tuple[str, str, str],
) -> dict[str, Any]:
    """Validate a de-identified aggregate metrics summary and recompute claims."""
    if not isinstance(payload, dict):
        raise JobValidationError("Aggregate metrics summary must be a JSON object")
    if "metrics" in payload:
        payload = payload["metrics"]
    if not isinstance(payload, dict):
        raise JobValidationError("Aggregate metrics must be a JSON object")
    allowed = {
        "schema_version",
        "mean_dice",
        "worst_site_dice",
        "site_dice_std",
        "hd95",
        "sites",
    }
    if set(payload) - allowed:
        raise JobValidationError("Aggregate metrics contain unsupported fields")
    sites = payload.get("sites")
    if not isinstance(sites, list) or len(sites) != 3:
        raise JobValidationError("Aggregate metrics require exactly three site summaries")
    normalized_sites: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in sites:
        if not isinstance(item, dict) or set(item) - {
            "site_id",
            "dice",
            "hd95",
            "sample_count",
        }:
            raise JobValidationError("Site aggregate metric fields are invalid")
        site_id = item.get("site_id")
        if not isinstance(site_id, str) or site_id not in expected_sites or site_id in seen:
            raise JobValidationError("Site aggregate metrics contain an invalid site identity")
        seen.add(site_id)
        dice = _finite_number(item.get("dice"), "dice")
        if not 0.0 <= dice <= 1.0:
            raise JobValidationError("Site Dice must be between zero and one")
        hd95_raw = item.get("hd95")
        hd95 = None if hd95_raw is None else _finite_number(hd95_raw, "hd95")
        if hd95 is not None and hd95 < 0:
            raise JobValidationError("Site HD95 must not be negative")
        sample_count = item.get("sample_count")
        if sample_count is not None and (
            isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count < 1
        ):
            raise JobValidationError("Site sample_count must be a positive integer")
        normalized_sites.append(
            {
                "site_id": site_id,
                "dice": dice,
                "hd95": hd95,
                **({"sample_count": sample_count} if sample_count is not None else {}),
            }
        )
    if seen != set(expected_sites):
        raise JobValidationError("Aggregate metrics do not cover the expected sites")
    normalized_sites.sort(key=lambda item: expected_sites.index(item["site_id"]))
    dice_values = [float(item["dice"]) for item in normalized_sites]
    computed = {
        "mean_dice": fmean(dice_values),
        "worst_site_dice": min(dice_values),
        "site_dice_std": pstdev(dice_values),
    }
    for key, expected in computed.items():
        claimed = _finite_number(payload.get(key), key)
        if not math.isclose(claimed, expected, rel_tol=1e-6, abs_tol=1e-6):
            raise JobValidationError(f"Aggregate metric {key} does not match site values")
    hd95_values = [float(item["hd95"]) for item in normalized_sites if item["hd95"] is not None]
    claimed_hd95 = payload.get("hd95")
    if claimed_hd95 is None:
        aggregate_hd95 = None
    else:
        aggregate_hd95 = _finite_number(claimed_hd95, "hd95")
        if aggregate_hd95 < 0:
            raise JobValidationError("Aggregate HD95 must not be negative")
        if len(hd95_values) != 3 or not math.isclose(
            aggregate_hd95,
            fmean(hd95_values),
            rel_tol=1e-6,
            abs_tol=1e-6,
        ):
            raise JobValidationError("Aggregate HD95 does not match site values")
    safe = {
        "schema_version": "rarelink-physical-aggregate-metrics-v1",
        **computed,
        "hd95": aggregate_hd95,
        "sites": normalized_sites,
        "site_count": 3,
        "patient_data_exported": False,
    }
    safe["receipt_sha256"] = hashlib.sha256(
        json.dumps(safe, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return safe


def load_aggregate_metrics(path: Path, expected_sites: tuple[str, str, str]) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise JobValidationError("Aggregate metrics artifact is unavailable") from exc
    if len(raw) > 2 * 1024 * 1024:
        raise JobValidationError("Aggregate metrics artifact exceeds the size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JobValidationError("Aggregate metrics artifact must be UTF-8 JSON") from exc
    return parse_aggregate_metrics(payload, expected_sites)
