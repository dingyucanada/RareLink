"""Deployment contracts for a physical multi-site RareLink federation.

This package deliberately contains topology and deployment metadata only. It
never loads medical images, dataset manifests, certificates, or private keys.
Those assets stay under each site's local administrative control.
"""

from rarelink.deployment.topology import (
    PhysicalTopology,
    SiteRuntime,
    load_physical_topology,
    load_site_runtime,
    render_nvflare_project,
)

__all__ = [
    "PhysicalTopology",
    "SiteRuntime",
    "load_physical_topology",
    "load_site_runtime",
    "render_nvflare_project",
]
