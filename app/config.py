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

    # moomoo OpenD, the local broker gateway. Not a secret: it is a loopback address.
    # SIMULATE by default so a fresh checkout cannot read a live trading account by accident.
    opend_host: str = "127.0.0.1"
    opend_port: int = 11111
    opend_market: str = "MY"
    #: The market whose trading account holds the positions. A moomoo ID can see one
    #: market's quotes and hold no trading account in it, so this is separate.
    opend_trade_market: str = "US"
    opend_trade_env: str = "SIMULATE"

    #: Serve the dashboard, live quotes and positions with NO sign-in.
    #: Off by default: on, anyone who can reach this port sees the account's positions.
    #: It is meant for local development on 127.0.0.1 — set it in .env, never in production.
    public_dashboard: bool = False
    #: MARKET.SYMBOL list shown on the public dashboard.
    demo_watchlist: str = "US.AAPL,HK.00700"
    #: How often the retained list is refreshed. One batched call covers all 100 symbols.
    market_refresh_seconds: int = 30
    #: How many stocks the dashboard lists, ranked by market value.
    market_top_n: int = 100
    #: Headlines for the dashboard, from Yahoo Finance's RSS feed (no key, no CORS).
    news_symbols: str = "AAPL,MSFT,NVDA,AMZN,TSLA"
    news_refresh_seconds: int = 600

    #: Paper-trading account: simulated cash, real prices, stored on this machine.
    paper_starting_cash: float = 100000.0
    paper_store_path: str = "data/paper.json"

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
