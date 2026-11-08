"""Application settings loaded from environment variables (and `.env` locally).

Only settings needed by the phases implemented so far live here; later phases add
their own (provider keys, run limits, ...). Secrets must use `SecretStr`.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["local", "test", "production"]

DEFAULT_DATABASE_URL = "postgresql+psycopg://agentops:agentops_dev@127.0.0.1:5432/agentops"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AgentOps Logistics API"
    app_env: AppEnv = "local"
    log_level: str = "INFO"
    git_sha: str = Field(default="dev", description="Set by the deploy platform/CI.")

    database_url: str = DEFAULT_DATABASE_URL
    migration_database_url: str | None = Field(
        default=None,
        description="Direct (non-pooled) URL for Alembic; falls back to database_url.",
    )
    db_connect_timeout_s: int = 5

    # Comma-separated list, e.g. "http://localhost:5173,https://app.vercel.app".
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def alembic_database_url(self) -> str:
        return self.migration_database_url or self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
