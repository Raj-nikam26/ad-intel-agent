"""config.py - centralized settings, loaded from environment/.env.

Every production service is optional. With nothing configured the app
runs entirely locally (SQLite, files on disk, in-process graph), which
is how the test suite runs. Set the variables below to switch each part
to its production backend independently.
"""

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

    # Local fallbacks.
    data_dir: str = "data"
    sample_file: str = "sample_data/Sample.xlsx"

    # PostgreSQL for sessions, versions, audit log and chat.
    # e.g. postgresql://adintel:adintel@localhost:5432/adintel
    database_url: str = ""

    # S3-compatible object storage for version snapshots (MinIO locally).
    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "adintel-snapshots"

    # Neo4j knowledge graph. Empty = in-process NetworkX graph.
    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # Sign-in (Clerk). Off by default so the public demo needs no account.
    auth_enabled: bool = False
    clerk_publishable_key: str = ""     # the JWKS URL and issuer are derived from this
    clerk_jwks_url: str = ""            # override only if not using the default domain
    clerk_issuer: str = ""
    clerk_authorized_parties: list[str] = []   # defaults to cors_allow_origins

    # Redis queue for graph sync. Empty = sync runs inline after each edit.
    redis_url: str = ""

    @property
    def resolved_data_dir(self) -> Path:
        p = Path(self.data_dir)
        return p if p.is_absolute() else BACKEND_DIR / p

    @property
    def resolved_sample_file(self) -> Path:
        p = Path(self.sample_file)
        return p if p.is_absolute() else BACKEND_DIR / p

    @property
    def use_postgres(self) -> bool:
        return self.database_url.startswith(("postgres://", "postgresql://"))

    @property
    def use_s3(self) -> bool:
        return bool(self.s3_endpoint_url)

    @property
    def use_neo4j(self) -> bool:
        return bool(self.neo4j_uri)


settings = Settings()
