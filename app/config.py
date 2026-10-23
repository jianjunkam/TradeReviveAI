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

    #: Where prices come from: "moomoo" (OpenD, needs a signed-in account on the same
    #: machine) or "yahoo" (HTTPS, no account — for a server that cannot run OpenD).
    data_source: str = "moomoo"
    yahoo_timeout: float = 12.0

    #: Close the demo pages (market, journal, papertrade, diagnosis) and serve the sign-in
    #: card instead. Off by default, because a demo that nobody can open is not a demo.
    demo_closed: bool = False

    #: AI features. The key lives only in .env on the server; the browser never sees it.
    deepseek_api_key: SecretStr | None = None
    ai_model: str = "deepseek-flash"
    ai_base_url: str = "https://api.deepseek.com"
    #: Fallback with no key: the Flowise chatflow already used by the Diagnosis page.
    flowise_host: str = "flowise.bdctraining.cloud"
    flowise_chatflow_id: str = "f2ac3baa-63d0-4ce2-ba69-07d8fa7b66c8"
    #: Retired: this used to gate the demo pages, and a stale `PUBLIC_DASHBOARD=false` in a
    #: deployed .env hid the entire product behind a login page whose email never arrives.
    #: Kept as a field so old configs load, never read as a gate. Use DEMO_CLOSED instead.
    public_dashboard: bool = True
    #: Put the login flow in front of /app. True by default: that is what the product
    #: does, and M1 asserts it. The demo env file sets it false so a reviewer lands inside.
    require_sign_in: bool = True
    #: A "sign in as the demo account" button that skips the email link and 2FA.
    #: There is no mail provider wired, so without this a hosted copy has no way in.
    #: Set false to remove the button and keep the email + passcode flow only.
    demo_sign_in: bool = True
    #: Include the broker account's OPEN POSITIONS in /api/public/market.
    #: Off by default: that is the one genuinely private thing the public pages could leak.
    public_positions: bool = False
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
    #: Loaded only when paper_store_path is missing: lets a host with no broker still
    #: show a populated journal. Fills are real historical prices, the money is not real.
    paper_seed_path: str = "demo/paper_seed.json"

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
