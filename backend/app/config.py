"""config.py - centralized settings, loaded from environment/.env."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ - relative paths below resolve against this, not the process
# working directory, so the server behaves the same however it is launched.
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: str = ""
    openrouter_model: str = "openrouter/auto"

    max_upload_size_mb: int = 25
    cors_allow_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    log_level: str = "INFO"

    # Where sessions, version snapshots and the audit log are stored.
    data_dir: str = "data"
    # The bundled demo file, offered to anyone who opens the app without one.
    sample_file: str = "sample_data/Sample.xlsx"

    @property
    def resolved_data_dir(self) -> Path:
        p = Path(self.data_dir)
        return p if p.is_absolute() else BACKEND_DIR / p

    @property
    def resolved_sample_file(self) -> Path:
        p = Path(self.sample_file)
        return p if p.is_absolute() else BACKEND_DIR / p


settings = Settings()
