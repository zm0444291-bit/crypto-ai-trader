from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Environment-backed runtime settings."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="local", alias="APP_ENV")
    app_name: str = Field(default="crypto-ai-trader", alias="APP_NAME")
    database_url: str = Field(
        default="sqlite:///./data/crypto_ai_trader.sqlite3",
        alias="DATABASE_URL",
    )
    config_dir: Path = Field(default=Path("config"), alias="CONFIG_DIR")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


def load_yaml_config(path: Path) -> dict[str, Any]:
    """Load a YAML config file and return a mapping."""

    with path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}

    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in YAML config: {path}")

    return loaded
