"""Validated, non-sensitive deployment contracts for physical FLARE sites."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SITE_ID = re.compile(r"^[a-z][a-z0-9-]{2,62}$")
ORG_ID = re.compile(r"^[a-z][a-z0-9_-]{2,62}$")
HOSTNAME = re.compile(
    r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[A-Za-z]{2,63}$"
)


class CoordinatorEndpoint(BaseModel):
    """The only network endpoint clients need to know about."""

    model_config = ConfigDict(extra="forbid")

    hostname: str
    fed_learn_port: int = Field(default=8002, ge=1, le=65535)
    admin_port: int = Field(default=8003, ge=1, le=65535)

    @field_validator("hostname")
    @classmethod
    def require_fqdn(cls, value: str) -> str:
        normalized = value.strip().lower().rstrip(".")
        if not HOSTNAME.fullmatch(normalized):
            raise ValueError("coordinator hostname must be a routable FQDN, not localhost or an IP")
        return normalized


class Coordinator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: CoordinatorEndpoint
    organization: str
    admin_identity: str

    @field_validator("organization")
    @classmethod
    def validate_org(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not ORG_ID.fullmatch(normalized):
            raise ValueError("organization must be a lower-case deployment identifier")
        return normalized

    @field_validator("admin_identity")
    @classmethod
    def validate_admin_identity(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("admin_identity must be an email-shaped NVFLARE admin identity")
        return normalized


class PhysicalSite(BaseModel):
    """A site identity. No data path or dataset metadata belongs in this file."""

    model_config = ConfigDict(extra="forbid")

    site_id: str
    organization: str
    spark_label: str = Field(description="Human-readable device label, never a serial number")

    @field_validator("site_id")
    @classmethod
    def validate_site_id(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not SITE_ID.fullmatch(normalized):
            raise ValueError("site_id must be a lower-case DNS-safe identifier")
        return normalized

    @field_validator("organization")
    @classmethod
    def validate_org(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not ORG_ID.fullmatch(normalized):
            raise ValueError("organization must be a lower-case deployment identifier")
        return normalized


class PhysicalTopology(BaseModel):
    """Central, reviewable topology for a real three-Spark federation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rarelink-physical-topology-v1"
    federation_name: str
    coordinator: Coordinator
    sites: list[PhysicalSite] = Field(min_length=3)

    @field_validator("federation_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not SITE_ID.fullmatch(normalized):
            raise ValueError("federation_name must be a lower-case deployment identifier")
        return normalized

    @model_validator(mode="after")
    def require_distinct_site_identities(self) -> PhysicalTopology:
        site_ids = [site.site_id for site in self.sites]
        organizations = [site.organization for site in self.sites]
        if len(site_ids) != len(set(site_ids)):
            raise ValueError("site_id values must be unique")
        if len(organizations) != len(set(organizations)):
            raise ValueError("each physical site must have an independent organization identity")
        if self.coordinator.organization in organizations:
            raise ValueError("coordinator organization must not be reused by a client site")
        return self

    def public_contract(self) -> dict[str, Any]:
        """Stable metadata safe to put in a deployment receipt and audit ledger."""
        return {
            "schema_version": self.schema_version,
            "federation_name": self.federation_name,
            "coordinator": {
                "hostname": self.coordinator.endpoint.hostname,
                "fed_learn_port": self.coordinator.endpoint.fed_learn_port,
                "admin_port": self.coordinator.endpoint.admin_port,
                "organization": self.coordinator.organization,
            },
            "sites": [
                {
                    "site_id": site.site_id,
                    "organization": site.organization,
                    "spark_label": site.spark_label,
                }
                for site in self.sites
            ],
            "raw_patient_data_in_topology": False,
        }


class SiteRuntime(BaseModel):
    """Local-only configuration that an individual hospital retains."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rarelink-site-runtime-v1"
    site_id: str
    dataset_manifest: Path
    dataset_root: Path | None = None
    dataset_receipt: Path | None = None
    artifact_root: Path
    startup_kit: Path
    required_free_memory_percent: int = Field(default=15, ge=5, le=80)

    @field_validator("site_id")
    @classmethod
    def validate_site_id(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not SITE_ID.fullmatch(normalized):
            raise ValueError("site_id must be a lower-case DNS-safe identifier")
        return normalized

    def safe_contract(self) -> dict[str, Any]:
        """Do not disclose local paths outside the hospital."""
        return {
            "schema_version": self.schema_version,
            "site_id": self.site_id,
            "dataset_manifest_present": self.dataset_manifest.exists(),
            "dataset_root_present": bool(
                self.dataset_root and self.dataset_root.exists()
            ),
            "dataset_receipt_present": bool(
                self.dataset_receipt and self.dataset_receipt.exists()
            ),
            "startup_kit_present": self.startup_kit.exists(),
            "artifact_root_present": self.artifact_root.exists(),
            "raw_patient_data_exported": False,
        }


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return payload


def load_physical_topology(path: Path) -> PhysicalTopology:
    return PhysicalTopology.model_validate(_load_yaml(path))


def load_site_runtime(path: Path) -> SiteRuntime:
    return SiteRuntime.model_validate(_load_yaml(path))


def render_nvflare_project(topology: PhysicalTopology) -> dict[str, Any]:
    """Render the source that ``nvflare provision`` signs."""
    endpoint = topology.coordinator.endpoint
    participants: list[dict[str, Any]] = [
        {
            "name": endpoint.hostname,
            "type": "server",
            "org": topology.coordinator.organization,
            "fed_learn_port": endpoint.fed_learn_port,
            "admin_port": endpoint.admin_port,
        }
    ]
    participants.extend(
        {"name": site.site_id, "type": "client", "org": site.organization}
        for site in topology.sites
    )
    participants.append(
        {
            "name": topology.coordinator.admin_identity,
            "type": "admin",
            "org": topology.coordinator.organization,
            "role": "project_admin",
        }
    )
    return {
        "api_version": 3,
        "name": topology.federation_name,
        "description": (
            "RareLink physical multi-Spark federation. Generated from a validated topology; "
            "regenerate instead of editing signed startup kits."
        ),
        "participants": participants,
        "builders": [
            {
                "path": "nvflare.lighter.impl.workspace.WorkspaceBuilder",
                "args": {"template_file": ["master_template.yml"]},
            },
            {
                "path": "nvflare.lighter.impl.static_file.StaticFileBuilder",
                "args": {"config_folder": "config"},
            },
            {"path": "nvflare.lighter.impl.cert.CertBuilder"},
            {"path": "nvflare.lighter.impl.signature.SignatureBuilder"},
        ],
    }


def topology_sha256(topology: PhysicalTopology) -> str:
    payload = json.dumps(topology.public_contract(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
