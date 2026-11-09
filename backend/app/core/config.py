"""Application settings loaded from environment variables (and `.env` locally).

Only settings needed by the phases implemented so far live here; later phases add
their own (provider keys, run limits, ...). Secrets must use `SecretStr`.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["local", "test", "production"]

DEFAULT_DATABASE_URL = "postgresql+psycopg://agentops:agentops_dev@127.0.0.1:5432/agentops"
# Repo-root data/ folder (scenarios, SOPs). backend/app/core/config.py -> parents[3] = repo root.
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
# Only for local development and tests; production refuses to start with it.
DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-me-0123456789"


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

    data_dir: Path = DEFAULT_DATA_DIR

    # Auth (Phase 1)
    jwt_secret: SecretStr = SecretStr(DEV_JWT_SECRET)
    jwt_expire_minutes: int = Field(default=120, ge=5, le=24 * 60)
    demo_login_enabled: bool = True
    login_rate_limit_per_minute: int = Field(default=10, ge=1)

    # LLM providers (used from Phase 6). Only "configured / not configured" is ever exposed.
    gemini_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    @field_validator("jwt_secret", mode="before")
    @classmethod
    def _empty_secret_means_unset(cls, value: object) -> object:
        # A blank `JWT_SECRET=` copied from .env.example falls back to the dev default.
        return DEV_JWT_SECRET if value in (None, "") else value

    @model_validator(mode="after")
    def _require_real_secret_in_production(self) -> "Settings":
        secret = self.jwt_secret.get_secret_value()
        if self.app_env == "production" and (secret == DEV_JWT_SECRET or len(secret) < 32):
            raise ValueError("JWT_SECRET must be set to a random value of 32+ characters")
        return self

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
