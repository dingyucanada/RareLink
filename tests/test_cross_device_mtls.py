import pytest

from rarelink.security import build_cross_device_mtls_evidence


def runtime(role: str, fingerprint: str) -> dict:
    return {
        "role": role,
        "platform": "Linux",
        "architecture": "arm64",
        "product": "test",
        "device_fingerprint": fingerprint,
    }


def test_cross_device_evidence_requires_reconnect_and_negative_control() -> None:
    report = build_cross_device_mtls_evidence(
        runtime("federation-server", "spark-hash"),
        runtime("federation-client", "mac-hash"),
        "Successfully registered client:site-c for project demo",
        "Successfully registered client:site-c for project demo",
        "TLS certificate verify failed: identity mismatch",
        "site-c",
        1,
    )

    assert report["same_physical_device"] is False
    assert report["registration"]["reconnect_succeeded"] is True
    assert report["negative_control"]["wrong_identity_rejected"] is True
    assert report["raw_logs_included"] is False


def test_cross_device_evidence_rejects_same_runtime() -> None:
    with pytest.raises(ValueError, match="distinct physical"):
        build_cross_device_mtls_evidence(
            runtime("federation-server", "same"),
            runtime("federation-client", "same"),
            "Successfully registered client:site-c",
            "Successfully registered client:site-c",
            "certificate verify failed",
            "site-c",
            1,
        )


def test_cross_device_evidence_classifies_startup_signature_rejection() -> None:
    report = build_cross_device_mtls_evidence(
        runtime("federation-server", "spark"),
        runtime("federation-client", "mac"),
        "Successfully registered client:site-c",
        "Successfully registered client:site-c",
        "Signature verification failed for client.crt",
        "site-c",
        1,
    )

    assert report["negative_control"]["reason_category"] == "startup_signature_rejection"


def test_cross_device_evidence_classifies_unsigned_startup_content() -> None:
    report = build_cross_device_mtls_evidence(
        runtime("federation-server", "spark"),
        runtime("federation-client", "mac"),
        "Successfully registered client:site-c",
        "Successfully registered client:site-c",
        "The following files are not secure content: client.crt client.key",
        "site-c",
        1,
    )

    assert report["negative_control"]["reason_category"] == "startup_signature_rejection"
