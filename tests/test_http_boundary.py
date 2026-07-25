import pytest

from rarelink.config import Settings
from rarelink.security.http_boundary import (
    PhysicalHTTPBoundaryError,
    validate_physical_cors,
)


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "http://rarelink.example.org",
        "https://user:password@rarelink.example.org",
        "https://rarelink.example.org/control",
        "https://rarelink.example.org?tenant=a",
    ],
)
def test_physical_mode_rejects_unsafe_cors_origins(origin: str) -> None:
    with pytest.raises(PhysicalHTTPBoundaryError):
        validate_physical_cors(
            Settings(
                _env_file=None,
                rarelink_physical_mode="physical",
                cors_origins=origin,
            )
        )


def test_physical_mode_accepts_exact_https_origins() -> None:
    settings = Settings(
        _env_file=None,
        rarelink_physical_mode="physical",
        cors_origins="https://rarelink-a.example.org,https://rarelink-b.example.org:9443",
    )
    assert validate_physical_cors(settings) == (
        "https://rarelink-a.example.org",
        "https://rarelink-b.example.org:9443",
    )


def test_nonphysical_mode_preserves_local_development_origin() -> None:
    settings = Settings(
        _env_file=None,
        rarelink_physical_mode="isolated-integration",
        cors_origins="http://localhost:5173",
    )
    assert validate_physical_cors(settings) == ("http://localhost:5173",)
