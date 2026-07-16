from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

REGISTRATION_PATTERN = re.compile(r"Successfully registered client:(?P<site>[^ ]+)")
REJECTION_PATTERNS = {
    "certificate_identity_mismatch": re.compile(
        r"(identity|certificate|participant).*(mismatch|not match|invalid)", re.IGNORECASE
    ),
    "tls_verification_failure": re.compile(
        r"(certificate verify failed|tls.*fail|ssl.*error)", re.IGNORECASE
    ),
    "authorization_rejection": re.compile(
        r"(not authorized|unauthorized|registration.*(reject|fail))", re.IGNORECASE
    ),
}


def _registered_site(log: str) -> str | None:
    matches = [REGISTRATION_PATTERN.search(line) for line in log.splitlines()]
    latest = next((match for match in reversed(matches) if match), None)
    return latest.group("site") if latest else None


def _rejection_category(log: str) -> str | None:
    for category, pattern in REJECTION_PATTERNS.items():
        if pattern.search(log):
            return category
    return None


def build_cross_device_mtls_evidence(
    server_runtime: dict[str, Any],
    client_runtime: dict[str, Any],
    initial_registration_log: str,
    reconnect_registration_log: str,
    rejection_log: str,
    expected_site: str,
    rejection_exit_code: int,
) -> dict[str, Any]:
    """Build token-free proof of physical separation, reconnect, and rejection."""
    server_fingerprint = server_runtime.get("device_fingerprint")
    client_fingerprint = client_runtime.get("device_fingerprint")
    if not server_fingerprint or not client_fingerprint:
        raise ValueError("Both device descriptors require a non-raw fingerprint")
    if server_fingerprint == client_fingerprint:
        raise ValueError("Cross-device evidence requires two distinct physical runtimes")
    initial_site = _registered_site(initial_registration_log)
    reconnect_site = _registered_site(reconnect_registration_log)
    if initial_site != expected_site or reconnect_site != expected_site:
        raise RuntimeError(f"Expected two secure registrations for {expected_site}")
    rejection_category = _rejection_category(rejection_log)
    if rejection_exit_code == 0 or not rejection_category:
        raise RuntimeError("Wrong-identity attempt lacks a classified non-zero rejection")

    safe_device_fields = ("role", "platform", "architecture", "product", "device_fingerprint")
    return {
        "schema_version": "rarelink-cross-device-mtls-v1",
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "connection_security": "mtls",
        "same_physical_device": False,
        "server_runtime": {
            field: server_runtime.get(field) for field in safe_device_fields
        },
        "client_runtime": {
            field: client_runtime.get(field) for field in safe_device_fields
        },
        "ssh_tunnel_used": True,
        "patient_data_transferred": False,
        "registration": {
            "site_id": expected_site,
            "initial_registration_succeeded": True,
            "dropout_simulated": True,
            "reconnect_succeeded": True,
            "successful_registration_count": 2,
        },
        "negative_control": {
            "wrong_identity_rejected": True,
            "exit_code_nonzero": True,
            "reason_category": rejection_category,
        },
        "raw_logs_included": False,
        "runtime_tokens_included": False,
        "claim_boundary": (
            "Two-device engineering rehearsal over an SSH tunnel; not a hospital WAN, "
            "availability benchmark, or production identity system."
        ),
    }
