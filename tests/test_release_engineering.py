from scripts.validate_release_engineering import validate_release_engineering


def test_release_engineering_contract_is_complete() -> None:
    receipt = validate_release_engineering()

    assert receipt["validated"] is True
    assert receipt["container_signing"] == "keyless-cosign"
    assert receipt["multi_arch"] == ["linux/amd64", "linux/arm64"]
    assert receipt["offline_arm64_bundle"] is True
    assert receipt["postgres_backup_restore"] is True
    assert receipt["prometheus"] is True
    assert receipt["opentelemetry"] is True
