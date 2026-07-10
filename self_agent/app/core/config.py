from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "个人工作助手"
    app_env: str = "development"
    api_prefix: str = "/api"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    default_model: str = "deepseek-chat"
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"

    database_url: str = "sqlite+aiosqlite:///./data/self_agent.db"
    qdrant_url: str = "http://localhost:6333"
    default_workspace_dir: str = Field(default_factory=lambda: str(Path.cwd()))
    log_retention_days: int = 90


@lru_cache
def get_settings() -> Settings:
    return Settings()

