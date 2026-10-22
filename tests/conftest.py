"""Test-wide fixtures and environment.

`APP_SECRET` is a fake value for the test process only: it is not a secret, it is not
used outside pytest, and no real key is ever written here.

The M3 fixtures add a real PostgreSQL. They are used only by the tests that need one;
the M0–M2 tests keep running with the in-memory stores.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

os.environ.setdefault("APP_SECRET", "test-only-app-secret-not-a-real-key")

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://testserver"

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://traderevive:traderevive_dev@localhost:5433/traderevive_test",
)

#: Every table in the M3 schema, in truncation order.
TABLES = (
    "users",
    "trading_accounts",
    "trades",
    "mistake_tags",
    "performance_metrics",
    "recovery_reports",
)


def _ensure_database(url: str) -> None:
    """Create the test database if it does not exist yet."""
    parsed = make_url(url)
    admin_url = parsed.set(database="postgres")
    db_name = parsed.database
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": db_name}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def db_engine():
    """A migrated PostgreSQL for the whole session."""
    from alembic import command
    from alembic.config import Config

    _ensure_database(TEST_DATABASE_URL)
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True, future=True)

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")

    yield engine
    engine.dispose()


@pytest.fixture
def db(db_engine):
    """An empty database for each test."""
    with db_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    yield db_engine


@pytest.fixture
def pg_env(db):
    """The app wired to PostgreSQL, with fakes where the network would otherwise be."""
    from app.auth.email import RecordingEmailSender
    from app.auth.google import FakeGoogleProvider, GoogleIdentity
    from app.auth.pg_store import PostgresAuthStore
    from app.config import Settings
    from app.main import create_app
    from app.repositories import SqlTenancy

    emails = RecordingEmailSender()
    store = PostgresAuthStore(db)
    tenancy = SqlTenancy(db)
    app = create_app(
        settings=Settings(app_secret="test-only-session-secret", environment="development"),
        store=store,
        tenancy=tenancy,
        email_sender=emails,
        google=FakeGoogleProvider(
            identity=GoogleIdentity(
                subject="g-1", email="google@example.com", email_verified=True, name="G"
            )
        ),
        clock=lambda: datetime.now(timezone.utc),
    )
    client = TestClient(app, base_url=BASE_URL, follow_redirects=False)

    env = SimpleNamespace(
        app=app,
        client=client,
        store=store,
        tenancy=tenancy,
        emails=emails,
        engine=db,
        new_client=lambda: TestClient(app, base_url=BASE_URL, follow_redirects=False),
        base_url=BASE_URL,
    )
    env.sign_in = lambda email, client=None: _sign_in(env, email, client or env.client)
    env.register = lambda email, name="Trader": _register(env, email, name)
    return env


def _register(env, email: str, name: str):
    return env.client.post("/auth/register", json={"email": email, "name": name})


def _sign_in(env, email: str, client: TestClient):
    """Magic link + second factor: a fully signed-in account owner."""
    if env.store.get_user_by_email(email) is None:
        response = _register(env, email, email.split("@")[0])
        assert response.status_code == 201, response.text
        env.emails.clear()

    requested = client.post("/auth/magic-link", data={"email": email})
    assert requested.status_code == 202, requested.text
    url = env.emails.last_url()
    assert url, "no magic link was recorded"
    env.emails.clear()
    assert client.get(urlsplit(url).path).status_code == 303

    user = env.store.get_user_by_email(email)
    code = pyotp.TOTP(user.totp_secret).now()
    assert client.post("/auth/2fa", data={"code": code}).status_code == 303
    return user
