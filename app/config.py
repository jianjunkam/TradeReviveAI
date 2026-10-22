"""Application settings: read from the environment, then from `.env`.

AGENTS.md: secrets come only from environment variables (.env), and must never be
written in code, a log or a response. Every secret is therefore held as a
``SecretStr``, whose repr is masked, so a stray ``print(settings)`` or a log record
cannot leak it.

The fields are exactly the list in docs/ARCHITECTURE.md, "Environment variables".
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """The confirmed stack's configuration, loaded from `.env` and the environment.

    Real environment variables win over `.env`, which is what lets the test suite run
    without touching a developer's local file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Required: the app must not start without a session secret.
    app_secret: SecretStr

    # Secure cookies everywhere by default: a deploy that forgets to set ENVIRONMENT
    # must not fall back to plain http and console-logged sign-in links.
    environment: str = "production"

    # Required from M3 (data model) onwards; optional while the skeleton has no tables.
    database_url: str | None = None

    # Required from M4 onwards.
    deepseek_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None

    # Required from M1 onwards.
    email_api_key: SecretStr | None = None
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None

    # Required from M7 onwards.
    whatsapp_access_token: SecretStr | None = None
    whatsapp_app_secret: SecretStr | None = None
    payment_api_key: SecretStr | None = None
    payment_webhook_secret: SecretStr | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings, read once from `.env`."""
    return Settings()
