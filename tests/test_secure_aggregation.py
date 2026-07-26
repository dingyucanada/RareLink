from __future__ import annotations

import pytest

from rarelink.security.secure_aggregation import assess_secure_aggregation_readiness


def test_secure_aggregation_assessment_is_fail_closed_and_deidentified() -> None:
    receipt = assess_secure_aggregation_readiness(
        expected_sites=("hospital-a", "hospital-b", "hospital-c"),
        required_quorum=3,
    )

    assert receipt["enabled"] is False
    assert receipt["decision"] in {
        "deferred-fail-closed",
        "eligible-for-physical-benchmark",
    }
    assert receipt["required_quorum"] == 3
    assert len(receipt["receipt_sha256"]) == 64
    serialized = str(receipt).lower()
    assert "patient" not in serialized
    assert "private key" not in serialized


def test_secure_aggregation_assessment_rejects_quorum_downgrade() -> None:
    with pytest.raises(ValueError, match="all expected sites"):
        assess_secure_aggregation_readiness(
            expected_sites=("hospital-a", "hospital-b", "hospital-c"),
            required_quorum=2,
        )


def test_secure_aggregation_assessment_rejects_duplicate_site_identity() -> None:
    with pytest.raises(ValueError, match="unique"):
        assess_secure_aggregation_readiness(
            expected_sites=("hospital-a", "hospital-a"),
            required_quorum=2,
        )
