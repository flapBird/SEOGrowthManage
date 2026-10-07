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
    # itch.io 新游雷达：高频轮询官方 RSS 只做"发现"，详情页补全每轮限量+限速
    # （itch 前置 WAF 会 429 限流，详情页抓取是主要风险点）。
    itch_radar_enabled: bool = True
    itch_radar_poll_interval_seconds: int = Field(default=300, ge=60)
    itch_radar_feeds: str = "https://itch.io/games/newest/free/html5/platform-web.xml"
    itch_radar_detail_batch: int = Field(default=10, ge=0, le=100)
    itch_radar_detail_delay_seconds: float = Field(default=4.0, ge=0.5, le=60)
    itch_radar_max_retries: int = Field(default=1, ge=0, le=5)
    # 出口代理（如本机 http://127.0.0.1:7890）；留空则跟随 HTTP(S)_PROXY 环境变量。
    itch_radar_proxy: str = ""

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
