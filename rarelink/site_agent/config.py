"""Local-only Site Agent configuration.

Values in this model stay on the hospital's Spark. API responses use
``safe_summary`` and therefore never expose filesystem paths or secrets.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SITE_ID = re.compile(r"^[a-z][a-z0-9-]{2,62}$")
SYSTEMD_SERVICE = re.compile(r"^[A-Za-z0-9_.@-]{1,120}\.service$")


class SiteAgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.site-agent",
        env_file_encoding="utf-8",
        env_prefix="RARELINK_SITE_AGENT_",
        extra="ignore",
    )

    site_id: str
    dataset_manifest: Path
    dataset_root: Path | None = None
    dataset_receipt: Path | None = None
    require_dataset_receipt: bool = True
    artifact_root: Path
    startup_kit: Path
    certificate_file: Path | None = None
    certificate_min_valid_days: int = Field(default=14, ge=1, le=180)
    require_certificate_under_startup_kit: bool = True
    state_database: Path = Path("/var/lib/rarelink/site-agent/state.sqlite3")
    api_token: SecretStr = Field(min_length=24)
    receipt_hmac_key: SecretStr = Field(min_length=32)
    bind_host: str = "127.0.0.1"
    port: int = Field(default=9100, ge=1, le=65535)
    required_free_memory_percent: float = Field(default=15, ge=5, le=80)
    required_free_disk_percent: float = Field(default=10, ge=2, le=80)
    required_gpu_free_memory_mib: int = Field(default=1024, ge=256, le=131_072)
    required_modules: str = "torch,monai,nvflare"
    executor_backend: Literal["disabled", "systemd"] = "disabled"
    nvflare_service_name: str = "rarelink-flare-client.service"

    @field_validator("site_id")
    @classmethod
    def validate_site_id(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not SITE_ID.fullmatch(normalized):
            raise ValueError("site_id must be a lower-case DNS-safe identifier")
        return normalized

    @field_validator("bind_host")
    @classmethod
    def validate_bind_host(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "0.0.0.0":  # noqa: S104 - ruff versions with security rules
            return normalized
        if normalized not in {"127.0.0.1", "::1"}:
            raise ValueError("bind_host must be loopback or 0.0.0.0 behind an mTLS proxy")
        return normalized

    @field_validator("nvflare_service_name")
    @classmethod
    def validate_nvflare_service_name(cls, value: str) -> str:
        normalized = value.strip()
        if not SYSTEMD_SERVICE.fullmatch(normalized):
            raise ValueError("nvflare_service_name must be a fixed systemd .service unit")
        return normalized

    @property
    def module_names(self) -> tuple[str, ...]:
        return tuple(item.strip() for item in self.required_modules.split(",") if item.strip())

    def safe_summary(self) -> dict[str, object]:
        return {
            "site_id": self.site_id,
            "manifest_configured": bool(str(self.dataset_manifest)),
            "dataset_root_configured": self.dataset_root is not None,
            "dataset_receipt_required": self.require_dataset_receipt,
            "dataset_receipt_configured": self.dataset_receipt is not None,
            "artifact_store_configured": bool(str(self.artifact_root)),
            "startup_kit_configured": bool(str(self.startup_kit)),
            "certificate_configured": self.certificate_file is not None,
            "certificate_min_valid_days": self.certificate_min_valid_days,
            "certificate_path_restricted": self.require_certificate_under_startup_kit,
            "required_modules": list(self.module_names),
            "executor_backend": self.executor_backend,
            "local_paths_exported": False,
            "secrets_exported": False,
            "patient_data_exported": False,
        }
