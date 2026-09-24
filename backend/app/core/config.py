from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "Passport API"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/postgres"
    # Session-pooler engine tuning: exactly one database connection per process.
    # GHL token refreshes reuse the caller's existing database session.
    db_pool_timeout_seconds: int = Field(default=10, ge=1, le=60)
    db_pool_recycle_seconds: int = Field(default=300, ge=60, le=3600)

    ghl_client_id: str = ""
    ghl_client_secret: str = ""
    ghl_app_id: str = ""
    ghl_app_shared_secret: str = ""
    ghl_token_encryption_key: str = ""
    ghl_oauth_redirect_uri: str = ""
    ghl_oauth_authorize_url: str = "https://marketplace.gohighlevel.com/oauth/chooselocation"
    ghl_parent_origins: Annotated[list[str], NoDecode] = []
    ghl_webhook_public_key: str = ""
    ghl_api_base_url: str = "https://services.leadconnectorhq.com"

    app_session_secret: str = "development-only-change-me"
    app_session_minutes: int = Field(default=15, ge=5, le=60)

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_platform_account_id: str = ""
    stripe_publishable_key: str = ""
    frontend_url: str = "http://localhost:5173"
    # NoDecode stops pydantic-settings from JSON-decoding the env value, so a
    # plain comma-separated string reaches split_origins() below.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    booking_hold_minutes: int = Field(default=10, ge=2, le=30)
    public_access_minutes: int = Field(default=60, ge=5, le=10_080)
    public_rate_limit_per_minute: int = Field(default=60, ge=10, le=10_000)
    waiver_public_days: int = Field(default=30, ge=1, le=365)
    outbox_lease_minutes: int = Field(default=15, ge=1, le=60)
    outbox_max_attempts: int = Field(default=12, ge=1, le=100)
    ghl_calendar_sync_enabled: bool = True
    # Existing GHL account-user directory sync is automatic after migration 012
    # and the users.readonly scope is available.
    ghl_staff_user_sync_enabled: bool = True
    # Used by the standalone worker. Vercel functions cannot keep a persistent
    # process alive, so production deployments should run backend/worker.py on
    # an always-on worker host for near-real-time synchronization.
    ghl_staff_sync_interval_seconds: int = Field(default=15, ge=10, le=60)
    cron_secret: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("ghl_parent_origins", mode="before")
    @classmethod
    def split_parent_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    def validate_runtime(self) -> None:
        if self.environment.lower() != "production":
            return
        required = {
            "GHL_CLIENT_ID": self.ghl_client_id,
            "GHL_CLIENT_SECRET": self.ghl_client_secret,
            "GHL_APP_ID": self.ghl_app_id,
            "GHL_APP_SHARED_SECRET": self.ghl_app_shared_secret,
            "GHL_TOKEN_ENCRYPTION_KEY": self.ghl_token_encryption_key,
            "GHL_OAUTH_REDIRECT_URI": self.ghl_oauth_redirect_uri,
            "GHL_WEBHOOK_PUBLIC_KEY": self.ghl_webhook_public_key,
            "GHL_PARENT_ORIGINS": ",".join(self.ghl_parent_origins),
            "APP_SESSION_SECRET": self.app_session_secret,
            "STRIPE_SECRET_KEY": self.stripe_secret_key,
            "STRIPE_WEBHOOK_SECRET": self.stripe_webhook_secret,
            "CRON_SECRET": self.cron_secret,
        }
        missing = [name for name, value in required.items() if not value]
        if self.app_session_secret == "development-only-change-me":
            missing.append("APP_SESSION_SECRET(non-default)")
        if missing:
            raise RuntimeError("Missing required production settings: " + ", ".join(missing))


@lru_cache
def get_settings() -> Settings:
    return Settings()
