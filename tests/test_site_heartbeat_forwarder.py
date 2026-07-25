import pytest

from scripts.push_site_heartbeat import build_forward_request


def envelope() -> dict:
    return {
        "site_id": "hospital-a",
        "timestamp": 1000,
        "heartbeat_id": "heartbeat-0001",
        "payload": {
            "heartbeat_id": "heartbeat-0001",
            "status": "READY",
            "contains_patient_data": False,
        },
        "payload_sha256": "a" * 64,
        "signature": "b" * 64,
    }


def test_forward_request_preserves_signature_without_credentials_in_body() -> None:
    request = build_forward_request(
        envelope(),
        "https://coordinator.example.org/",
        "demo-access-token",
    )

    assert request.url.endswith("/api/physical/sites/hospital-a/heartbeat")
    assert request.headers["X-RareLink-Site-Signature"] == "b" * 64
    assert request.headers["X-RareLink-Demo-Token"] == "demo-access-token"
    assert b"demo-access-token" not in request.body
    assert b"patient" in request.body
    assert b"true" not in request.body


def test_forward_request_rejects_patient_data_and_mismatched_id() -> None:
    unsafe = envelope()
    unsafe["payload"]["contains_patient_data"] = True
    with pytest.raises(ValueError, match="exclude patient data"):
        build_forward_request(unsafe, "https://coordinator.example.org")

    mismatch = envelope()
    mismatch["payload"]["heartbeat_id"] = "heartbeat-other"
    with pytest.raises(ValueError, match="IDs do not match"):
        build_forward_request(mismatch, "https://coordinator.example.org")
