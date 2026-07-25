import pytest

from rarelink.security import heartbeat_signature, verify_heartbeat_signature


def test_signed_heartbeat_is_verified_without_returning_secret() -> None:
    payload = {"status": "READY", "contains_patient_data": False}
    signature = heartbeat_signature("hospital-a", 1000, "heartbeat-001", payload, "secret")

    digest = verify_heartbeat_signature(
        site_id="hospital-a",
        timestamp=1000,
        heartbeat_id="heartbeat-001",
        payload=payload,
        secret="secret",
        signature=signature,
        max_age_seconds=60,
        now=1020,
    )

    assert len(digest) == 64
    assert "secret" not in digest


def test_heartbeat_rejects_tampering_and_replay() -> None:
    payload = {"status": "READY"}
    signature = heartbeat_signature("hospital-a", 1000, "heartbeat-001", payload, "secret")

    with pytest.raises(ValueError, match="signature"):
        verify_heartbeat_signature(
            site_id="hospital-a",
            timestamp=1000,
            heartbeat_id="heartbeat-001",
            payload={"status": "TRAINING"},
            secret="secret",
            signature=signature,
            max_age_seconds=60,
            now=1020,
        )

    with pytest.raises(ValueError, match="replay window"):
        verify_heartbeat_signature(
            site_id="hospital-a",
            timestamp=1000,
            heartbeat_id="heartbeat-001",
            payload=payload,
            secret="secret",
            signature=signature,
            max_age_seconds=60,
            now=1200,
        )
