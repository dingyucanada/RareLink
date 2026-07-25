import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./artifacts/rarelink.db"
    artifact_root: Path = Path("./artifacts")
    data_root: Path = Path("./data/runtime")

    # Step Plan uses an OpenAI-compatible endpoint. Keep this default aligned
    # with the competition plan endpoint so a deployment does not silently
    # fall back to an unrelated /v1 route when STEP_API_BASE is omitted.
    step_api_base: str = "https://api.stepfun.com/step_plan/v1"
    step_api_key: str = ""
    step_model: str = "step-3.7-flash"
    step_timeout_seconds: float = 60

    # Agent routing. Step 3.7 stays available for the competition integration,
    # while a TensorRT-LLM endpoint on the DGX Spark can process approved
    # aggregate research context without leaving the local network.
    rarelink_agent_backend: str = "hybrid"
    rarelink_spark_llm_base: str = "http://127.0.0.1:8355/v1"
    spark_llm_model: str = "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4"
    spark_llm_timeout_seconds: float = 180

    rarelink_min_group_size: int = 5
    rarelink_allow_llm: bool = True
    rarelink_demo_cache: bool = False
    rarelink_fl_mode: str = "mock"
    rarelink_demo_access_token: str = ""
    rarelink_simulate_training_failure: bool = False
    # Interim P0 authentication for Site Agent heartbeats. Values are supplied
    # only through the runtime environment as a JSON mapping. Production P1
    # replaces this with hospital OIDC/mTLS identity and a managed secret store.
    rarelink_physical_site_secrets: str = ""
    rarelink_physical_operator_token: str = ""
    rarelink_audit_hmac_key: str = ""
    rarelink_physical_mode: Literal[
        "disabled", "isolated-integration", "physical"
    ] = "disabled"
    rarelink_physical_auth_mode: Literal["legacy-token", "oidc"] = "legacy-token"
    rarelink_physical_heartbeat_max_age_seconds: int = 300
    rarelink_physical_approval_ttl_seconds: int = Field(
        default=86400,
        ge=300,
        le=604800,
    )
    rarelink_oidc_issuer: str = ""
    rarelink_oidc_audience: str = ""
    rarelink_oidc_jwks_json: str = ""
    rarelink_oidc_roles_claim: str = "roles"
    rarelink_oidc_organization_claim: str = "organization"
    rarelink_oidc_sites_claim: str = "site_ids"
    rarelink_nvflare_admin_kit: str = ""
    rarelink_nvflare_executable: str = "nvflare"
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def physical_site_secret_map(self) -> dict[str, str]:
        if not self.rarelink_physical_site_secrets:
            return {}
        value = json.loads(self.rarelink_physical_site_secrets)
        if not isinstance(value, dict) or not all(
            isinstance(key, str) and isinstance(secret, str) and secret
            for key, secret in value.items()
        ):
            raise ValueError("RARELINK_PHYSICAL_SITE_SECRETS must be a JSON string map")
        return value

    @property
    def physical_oidc_jwks(self) -> dict[str, object]:
        if not self.rarelink_oidc_jwks_json:
            return {}
        value = json.loads(self.rarelink_oidc_jwks_json)
        if not isinstance(value, dict) or not isinstance(value.get("keys"), list):
            raise ValueError("RARELINK_OIDC_JWKS_JSON must be a JWKS object")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
