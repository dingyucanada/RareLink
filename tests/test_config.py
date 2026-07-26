from rarelink.config import Settings


def test_cors_origins_accept_comma_separated_environment_value(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173,https://demo.example")

    settings = Settings(_env_file=None)

    assert settings.cors_origin_list == ["http://localhost:5173", "https://demo.example"]


def test_physical_site_secrets_are_parsed_only_from_runtime_configuration() -> None:
    settings = Settings(
        _env_file=None,
        rarelink_physical_site_secrets='{"hospital-a":"secret-a"}',
    )

    assert settings.physical_site_secret_map == {"hospital-a": "secret-a"}


def test_physical_control_plane_is_fail_closed_by_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.rarelink_physical_mode == "disabled"
    assert settings.rarelink_physical_auth_mode == "legacy-token"
    assert settings.rarelink_audit_hmac_key == ""


def test_oidc_jwks_refresh_settings_are_bounded_and_parse_an_exact_allowlist() -> None:
    settings = Settings(
        _env_file=None,
        rarelink_oidc_jwks_uri="https://idp.hospital.example/keys",
        rarelink_oidc_jwks_allowed_uris_json=(
            '["https://idp.hospital.example/keys",'
            '"https://idp.hospital.example/keys-next"]'
        ),
        rarelink_oidc_jwks_timeout_seconds=2.5,
        rarelink_oidc_jwks_max_response_bytes=65536,
        rarelink_oidc_jwks_cache_ttl_seconds=600,
        rarelink_oidc_jwks_old_key_grace_seconds=90,
    )

    assert settings.physical_oidc_jwks_allowed_uris == frozenset(
        {
            "https://idp.hospital.example/keys",
            "https://idp.hospital.example/keys-next",
        }
    )
    assert settings.rarelink_oidc_jwks_timeout_seconds == 2.5
    assert settings.rarelink_oidc_jwks_max_response_bytes == 65536
    assert settings.rarelink_oidc_jwks_cache_ttl_seconds == 600
    assert settings.rarelink_oidc_jwks_old_key_grace_seconds == 90
