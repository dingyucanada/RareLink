from rarelink.config import Settings


def test_cors_origins_accept_comma_separated_environment_value(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173,https://demo.example")

    settings = Settings(_env_file=None)

    assert settings.cors_origin_list == ["http://localhost:5173", "https://demo.example"]
