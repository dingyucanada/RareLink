from functools import lru_cache
from pathlib import Path

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
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
