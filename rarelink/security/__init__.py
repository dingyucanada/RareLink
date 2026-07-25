"""Security evidence helpers for federation and Agent boundaries."""

from rarelink.security.mtls import build_cross_device_mtls_evidence
from rarelink.security.oidc import (
    OfflineOIDCAdapter,
    OIDCClaimsConfig,
    OIDCConfigurationError,
    OIDCValidationError,
)
from rarelink.security.physical_rbac import (
    PhysicalPermission,
    PhysicalPermissionDenied,
    PhysicalPrincipal,
    PhysicalRole,
    PhysicalSiteScopeDenied,
    require_permission,
    require_site_scope,
)
from rarelink.security.site_auth import (
    heartbeat_signature,
    payload_sha256,
    verify_heartbeat_signature,
)

__all__ = [
    "build_cross_device_mtls_evidence",
    "heartbeat_signature",
    "OfflineOIDCAdapter",
    "OIDCClaimsConfig",
    "OIDCConfigurationError",
    "OIDCValidationError",
    "payload_sha256",
    "PhysicalPermission",
    "PhysicalPermissionDenied",
    "PhysicalPrincipal",
    "PhysicalRole",
    "PhysicalSiteScopeDenied",
    "require_permission",
    "require_site_scope",
    "verify_heartbeat_signature",
]
