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
