"""HTTP boundary rules for the physical control plane."""

from __future__ import annotations

from urllib.parse import urlsplit

from rarelink.config import Settings


class PhysicalHTTPBoundaryError(ValueError):
    pass


def validate_physical_cors(config: Settings) -> tuple[str, ...]:
    origins = tuple(config.cors_origin_list)
    if config.rarelink_physical_mode != "physical":
        return origins
    if not origins:
        raise PhysicalHTTPBoundaryError("Physical mode requires an explicit HTTPS CORS origin")
    for origin in origins:
        parsed = urlsplit(origin)
        if (
            origin == "*"
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise PhysicalHTTPBoundaryError(
                "Physical mode CORS origins must be exact HTTPS origins without credentials"
            )
    return origins
