"""TradeRevive AI — the FastAPI application.

M1 added sign-in. M2 puts the permission matrix in front of it: every router runs the
guard, every route declares what it needs, and an undeclared route is refused. The data
model (M3), the AI calls (M4/M5) and billing (M7) still arrive in their own milestones.

Everything the routes touch is built here and reachable as `app.state`, so a test (or
M3's Postgres store) can replace one piece without touching the route code.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal
from typing import Callable

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth.email import EmailSender, build_email_sender
from app.auth.google import GoogleProvider, build_google_provider
from app.auth.pg_store import PostgresAuthStore
from app.auth.store import AuthStore, InMemoryAuthStore
from app.broker.base import Broker
from app.broker.yahoo import YahooBroker
from app.config import Settings, get_settings
from app.db import make_engine
from app.market import MarketCache
from app.news import NewsFeed
from app.paper import PaperStore
from app.permissions import guard, public
from app.repositories import SqlTenancy
from app.routes import admin as admin_routes
from app.routes import auth as auth_routes
from app.routes import broker as broker_routes
from app.routes import pages as page_routes
from app.routes import journal as journal_routes
from app.routes import diagnosis as diagnosis_routes
from app.routes import paper as paper_routes
from app.routes import public as public_routes
from app.routes import trades as trade_routes
from app.tenancy import TenancyStore

logger = logging.getLogger("app.main")

SESSION_COOKIE = "tr_session"
SESSION_MAX_AGE = 8 * 60 * 60  # one working day
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "static"


def _project_path(value: str) -> str:
    """Anchor a configured path to the repo, not to wherever uvicorn was started."""
    path = Path(value)
    return str(path if path.is_absolute() else PROJECT_ROOT / path)


def create_app(
    settings: Settings | None = None,
    *,
    store: AuthStore | None = None,
    email_sender: EmailSender | None = None,
    google: GoogleProvider | None = None,
    clock: Callable[[], datetime] | None = None,
    tenancy: TenancyStore | None = None,
    broker: Broker | None = None,
    market: MarketCache | None = None,
    paper: PaperStore | None = None,
) -> FastAPI:
    """Build the app. Settings and dependencies are injectable; production uses the defaults."""
    resolved = settings if settings is not None else get_settings()

    app = FastAPI(
        title="TradeRevive AI",
        version="0.3.0",
        # The schema publishes the whole permission matrix. Off outside development.
        docs_url="/docs" if resolved.environment == "development" else None,
        redoc_url="/redoc" if resolved.environment == "development" else None,
        openapi_url="/openapi.json" if resolved.environment == "development" else None,
    )
    app.state.settings = resolved
    logger.info(
        "demo pages=%s | sign-in required=%s | positions public=%s | environment=%s",
        "closed" if resolved.demo_closed else "open",
        resolved.require_sign_in,
        resolved.public_positions,
        resolved.environment,
    )

    engine = None
    if store is None or tenancy is None:
        if resolved.database_url:
            engine = make_engine(resolved.database_url)
        elif resolved.environment != "development" and resolved.require_sign_in:
            # Refusing here protects real accounts: an in-memory store loses every trade on
            # restart. It only applies when the authenticated product is actually in use.
            raise RuntimeError(
                "DATABASE_URL is required outside development: refusing to start without "
                "a real database."
            )
        elif resolved.environment != "development":
            logger.warning(
                "No DATABASE_URL and REQUIRE_SIGN_IN is off: serving the demo from memory. "
                "Accounts and orders are lost on restart."
            )
    app.state.engine = engine

    app.state.store = (
        store
        if store is not None
        else (PostgresAuthStore(engine) if engine is not None else InMemoryAuthStore())
    )
    app.state.tenancy = (
        tenancy
        if tenancy is not None
        else (SqlTenancy(engine) if engine is not None else TenancyStore())
    )
    app.state.email_sender = (
        email_sender if email_sender is not None else build_email_sender(resolved)
    )
    app.state.google = google if google is not None else build_google_provider(resolved)
    app.state.clock = clock or (lambda: datetime.now(timezone.utc))
    # The broker only ever reads: construction opens no connection, and every call either
    # returns what the source reported or raises BrokerUnavailable.
    # Prices come from Yahoo Finance over HTTPS: no gateway to install, no account to
    # sign in, nothing native to break on a host we do not control.
    app.state.broker = (
        broker
        if broker is not None
        else YahooBroker(timeout=resolved.yahoo_timeout, universe_size=resolved.market_top_n)
    )

    # One sweep of the whole US market, refreshed on a timer and served from memory:
    # 7,000 snapshots per page view is not possible, and sorting across the market needs
    # every row. The thread only starts when the public dashboard can actually use it.
    app.state.market = market if market is not None else MarketCache(
        app.state.broker,
        refresh_seconds=resolved.market_refresh_seconds,
        top_n=resolved.market_top_n,
    )
    if not resolved.demo_closed and market is None:
        app.state.market.start()

    # Headlines are fetched server-side and cached: Yahoo sends no CORS headers, so the
    # browser could not call it directly.
    app.state.news = NewsFeed(
        symbols=resolved.news_symbols,
        refresh_seconds=resolved.news_refresh_seconds,
    )

    # Simulated money, real prices. The file lives on this machine so a restart keeps the
    # demo account; nothing here can reach a real trading account.
    app.state.paper = paper if paper is not None else PaperStore(
        _project_path(resolved.paper_store_path),
        starting_cash=Decimal(str(resolved.paper_starting_cash)),
        seed_path=_project_path(resolved.paper_seed_path),
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=resolved.app_secret.get_secret_value(),
        session_cookie=SESSION_COOKIE,
        max_age=SESSION_MAX_AGE,
        same_site="lax",
        https_only=resolved.environment != "development",
    )

    @app.get("/health", dependencies=[Depends(guard)])
    @public
    def health() -> dict[str, str]:
        """Liveness only: the process is up. It deliberately checks no dependency."""
        return {"status": "ok"}

    # Assets are public by nature (they are what the browser needs before sign-in).
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def _dashboard_page(name: str) -> Response:
        """The public pages exist only when the dashboard is switched on."""
        if resolved.demo_closed:
            return RedirectResponse("/sign-in", status_code=303)
        return FileResponse(STATIC_DIR / name)

    @app.get("/demo", dependencies=[Depends(guard)])
    @public
    def demo() -> Response:
        """A design preview with sample data: no account, no sign-in, no model call."""
        return FileResponse(STATIC_DIR / "journal.html")

    @app.get("/", dependencies=[Depends(guard)])
    @public
    def home() -> Response:
        """The front door: the market dashboard."""
        return _dashboard_page("market.html")

    @app.get("/journal", dependencies=[Depends(guard)])
    @public
    def journal() -> Response:
        """Net P&L, win rate, equity curve, mistake breakdown."""
        return _dashboard_page("journal.html")

    @app.get("/papertrade", dependencies=[Depends(guard)])
    @public
    def papertrade() -> Response:
        """Simulated trading at real prices. No order ever leaves this machine."""
        return _dashboard_page("papertrade.html")

    @app.get("/diagnosis", dependencies=[Depends(guard)])
    @public
    def diagnosis() -> Response:
        """The Flowise assistant. The page it serves holds only a public chatflow id."""
        return _dashboard_page("diagnosis.html")

    # Every router runs the guard, so no route reaches its handler unpermissioned.
    app.include_router(auth_routes.router, dependencies=[Depends(guard)])
    app.include_router(page_routes.router, dependencies=[Depends(guard)])
    app.include_router(admin_routes.router, dependencies=[Depends(guard)])
    app.include_router(trade_routes.router, dependencies=[Depends(guard)])
    app.include_router(broker_routes.router, dependencies=[Depends(guard)])
    app.include_router(public_routes.router, dependencies=[Depends(guard)])
    app.include_router(paper_routes.router, dependencies=[Depends(guard)])
    app.include_router(journal_routes.router, dependencies=[Depends(guard)])
    app.include_router(diagnosis_routes.router, dependencies=[Depends(guard)])
    return app


app = create_app()
