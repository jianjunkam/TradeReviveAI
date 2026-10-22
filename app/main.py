"""TradeRevive AI — the FastAPI application.

M1 added sign-in. M2 puts the permission matrix in front of it: every router runs the
guard, every route declares what it needs, and an undeclared route is refused. The data
model (M3), the AI calls (M4/M5) and billing (M7) still arrive in their own milestones.

Everything the routes touch is built here and reachable as `app.state`, so a test (or
M3's Postgres store) can replace one piece without touching the route code.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from fastapi import Depends, FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.auth.email import EmailSender, build_email_sender
from app.auth.google import GoogleProvider, build_google_provider
from app.auth.pg_store import PostgresAuthStore
from app.auth.store import AuthStore, InMemoryAuthStore
from app.config import Settings, get_settings
from app.db import make_engine
from app.permissions import guard, public
from app.repositories import SqlTenancy
from app.routes import admin as admin_routes
from app.routes import auth as auth_routes
from app.routes import pages as page_routes
from app.routes import trades as trade_routes
from app.tenancy import TenancyStore

SESSION_COOKIE = "tr_session"
SESSION_MAX_AGE = 8 * 60 * 60  # one working day


def create_app(
    settings: Settings | None = None,
    *,
    store: AuthStore | None = None,
    email_sender: EmailSender | None = None,
    google: GoogleProvider | None = None,
    clock: Callable[[], datetime] | None = None,
    tenancy: TenancyStore | None = None,
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

    engine = None
    if store is None or tenancy is None:
        if resolved.database_url:
            engine = make_engine(resolved.database_url)
        elif resolved.environment != "development":
            # Better to refuse to boot than to serve traffic from a process-local store
            # that loses every trade on restart.
            raise RuntimeError(
                "DATABASE_URL is required outside development: refusing to start without "
                "a real database."
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

    # Secure cookies are on everywhere but local development, where the app is served
    # over plain http://127.0.0.1 and a Secure cookie would never be sent back.
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

    # Every router runs the guard, so no route reaches its handler unpermissioned.
    app.include_router(auth_routes.router, dependencies=[Depends(guard)])
    app.include_router(page_routes.router, dependencies=[Depends(guard)])
    app.include_router(admin_routes.router, dependencies=[Depends(guard)])
    app.include_router(trade_routes.router, dependencies=[Depends(guard)])
    return app


app = create_app()
