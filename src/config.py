"""
アプリケーション設定。

pydantic-settings を使用し、環境変数や .env ファイルからも読み込める。
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CHARAPP_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Wizmy"
    data_dir: Path = Path("data")
    host: str = "0.0.0.0"
    port: int = 8080
    reload: bool = False
    log_level: str = "info"
    storage_secret: str = "charapp-dev-only-secret"

    @property
    def config_file(self) -> Path:
        return self.data_dir / "config.json"

    @property
    def db_file(self) -> Path:
        return self.data_dir / "characters.db"


_settings: AppSettings | None = None


def get_settings() -> AppSettings:
    global _settings
    if _settings is None:
        _settings = AppSettings()
    return _settings
