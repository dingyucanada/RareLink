from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./artifacts/rarelink.db"
    artifact_root: Path = Path("./artifacts")
    data_root: Path = Path("./data/runtime")

    step_api_base: str = "https://api.stepfun.com/v1"
    step_api_key: str = ""
    step_model: str = "step-3.7-flash"
    step_timeout_seconds: float = 60

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
