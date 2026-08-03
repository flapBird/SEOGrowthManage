from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_name: str = "SEO 增长工作台"
    admin_username: str = ""
    admin_password: str = ""
    session_secret: str = ""
    session_days: int = 7
    cookie_secure: bool = False
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'backlink_manager.db'}"
    fernet_key: str = ""
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = Field(default=60, ge=5)
    automation_batch_size: int = Field(default=10, ge=1, le=100)
    automation_max_retries: int = Field(default=3, ge=0, le=20)
    playwright_headless: bool = True
    keyword_discovery_enabled: bool = True
    keyword_fetch_interval_seconds: int = Field(default=1800, ge=60)
    keyword_enrichment_interval_seconds: int = Field(default=900, ge=60)
    keyword_enrichment_batch_size: int = Field(default=5, ge=1, le=50)
    keyword_serpapi_daily_budget: int = Field(default=50, ge=0, le=10000)
    keyword_ignore_cooldown_days: int = Field(default=30, ge=1, le=365)

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    @field_validator("admin_username", "admin_password", "session_secret", "fernet_key")
    @classmethod
    def required_in_runtime(cls, value: str) -> str:
        return value.strip()

    def validate_secrets(self) -> None:
        missing = [
            name
            for name in ("admin_username", "admin_password", "session_secret", "fernet_key")
            if not getattr(self, name)
        ]
        if missing:
            raise RuntimeError(f"缺少必需环境变量: {', '.join(name.upper() for name in missing)}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
