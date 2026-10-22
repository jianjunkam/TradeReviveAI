"""Broker integration: it reports what OpenD says, and never invents a price.

The dangerous failure for this feature is not an exception — it is a plausible-looking
number that is not live. These tests pin the honest behaviours: "not connected" is a
normal answer, a bad symbol is explained, and no payload ever carries a made-up price.
"""

from __future__ import annotations

import socket
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

import pyotp
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.auth.email import RecordingEmailSender
from app.auth.store import InMemoryAuthStore
from app.broker.base import BrokerUnavailable, Position, Quote
from app.broker.fake import FakeBroker
from app.broker.moomoo import MoomooBroker, _quote_from_row
from app.config import Settings
from app.main import create_app
from app.tenancy import TenancyStore

BASE_URL = "https://testserver"


def _closed_port() -> int:
    """A port nothing is listening on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ------------------------------------------------------------------ the adapter


def test_status_reports_not_connected_when_opend_is_absent():
    broker = MoomooBroker("127.0.0.1", _closed_port())

    status = broker.status()

    assert status.connected is False
    assert str(status.port) in status.reason
    assert "OpenD" in status.reason, "the reason must name what to start"


def test_symbol_must_carry_a_market_prefix():
    broker = MoomooBroker("127.0.0.1", _closed_port())

    with pytest.raises(BrokerUnavailable) as failure:
        broker.quote("AAPL")

    assert "MARKET.SYMBOL" in str(failure.value)
    assert "MY.5225" in str(failure.value)


def test_snapshot_row_maps_to_a_quote():
    row = {
        "code": "MY.5225",
        "name": "MAYBANK",
        "last_price": 6.8,
        "prev_close_price": 6.7,
        "change_rate": 1.49,
        "volume": 123400,
        "bid_price": 6.79,
        "ask_price": 6.8,
        "update_time": "2026-10-22 15:30:00",
    }

    quote = _quote_from_row("MY.5225", row)

    assert quote.symbol == "MY.5225"
    assert quote.last_price == 6.8
    assert quote.previous_close == 6.7
    assert quote.bid == 6.79 and quote.ask == 6.8
    # OpenD does not report freshness per snapshot; unknown is not the same as live.
    assert quote.delayed is None


def test_snapshot_without_a_price_is_an_error_not_a_zero():
    with pytest.raises(BrokerUnavailable):
        _quote_from_row("MY.9999", {"code": "MY.9999"})


def test_change_rate_is_derived_when_the_snapshot_omits_it():
    """OpenD's snapshot has no change_rate. 343.99 against 339.50 is +1.32%, not 0.0%."""
    row = {"code": "US.AAPL", "last_price": 343.99, "prev_close_price": 339.5, "volume": 1}

    quote = _quote_from_row("US.AAPL", row)

    assert quote.change_rate == 1.32, "a missing change_rate must be computed, not zeroed"


def test_quote_fails_fast_when_opend_is_absent():
    """The SDK retries a missing OpenD forever; a web request must not wait for it."""
    broker = MoomooBroker("127.0.0.1", _closed_port(), connect_timeout=0.4, call_timeout=2)

    started = time.monotonic()
    with pytest.raises(BrokerUnavailable) as failure:
        broker.quote("MY.5225")
    elapsed = time.monotonic() - started

    assert elapsed < 3.0, f"took {elapsed:.1f}s — the SDK retry loop leaked into the request"
    assert "not listening" in str(failure.value)


def test_positions_fail_fast_when_opend_is_absent():
    broker = MoomooBroker("127.0.0.1", _closed_port(), connect_timeout=0.4, call_timeout=2)

    started = time.monotonic()
    with pytest.raises(BrokerUnavailable):
        broker.positions()

    assert time.monotonic() - started < 3.0


def test_app_uses_the_real_broker_by_default():
    """FakeBroker must never be reachable from a normal build."""
    app = create_app(settings=Settings(app_secret="test-only", environment="development"))

    assert isinstance(app.state.broker, MoomooBroker)


# ------------------------------------------------------------------- endpoints


def _sign_in(client: TestClient, store: InMemoryAuthStore, emails: RecordingEmailSender, email: str):
    assert client.post("/auth/register", json={"email": email, "name": "B"}).status_code == 201
    emails.clear()
    assert client.post("/auth/magic-link", data={"email": email}).status_code == 202
    url = emails.last_url()
    emails.clear()
    assert client.get(urlsplit(url).path).status_code == 303
    user = store.get_user_by_email(email)
    code = pyotp.TOTP(user.totp_secret).now()
    assert client.post("/auth/2fa", data={"code": code}).status_code == 303


@pytest.fixture
def broker_env():
    store = InMemoryAuthStore()
    emails = RecordingEmailSender()
    fake = FakeBroker(
        connected=True,
        quotes={
            "MY.5225": Quote(
                symbol="MY.5225",
                name="MAYBANK",
                last_price=6.8,
                previous_close=6.7,
                change_rate=1.49,
                volume=123400,
                bid=6.79,
                ask=6.8,
                updated_at="2026-10-22 15:30:00",
            )
        },
        positions=[
            Position(
                symbol="MY.5225",
                name="MAYBANK",
                quantity=1000,
                cost_price=6.4,
                market_price=6.8,
                market_value=6800.0,
                unrealised_pl=400.0,
            )
        ],
    )
    app = create_app(
        settings=Settings(app_secret="test-only", environment="development"),
        store=store,
        tenancy=TenancyStore(),
        email_sender=emails,
        broker=fake,
    )
    client = TestClient(app, base_url=BASE_URL, follow_redirects=False)
    _sign_in(client, store, emails, "broker@example.com")
    return SimpleNamespace(client=client, app=app, broker=fake)


def test_status_says_connected_when_opend_answers(broker_env):
    response = broker_env.client.get("/api/broker/status")

    assert response.status_code == 200
    assert response.json()["connected"] is True
    assert response.json()["host"] == "127.0.0.1"


def test_quote_is_returned_exactly_as_reported(broker_env):
    response = broker_env.client.get("/api/broker/quote", params={"symbol": "MY.5225"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["last_price"] == 6.8
    assert body["previous_close"] == 6.7
    assert body["source"] == "moomoo OpenD"
    assert body["updated_at"] == "2026-10-22 15:30:00"


def test_positions_are_returned(broker_env):
    response = broker_env.client.get("/api/broker/positions")

    assert response.status_code == 200, response.text
    positions = response.json()["positions"]
    assert len(positions) == 1
    assert positions[0]["symbol"] == "MY.5225"
    assert positions[0]["unrealised_pl"] == 400.0


def test_broker_endpoints_need_a_signed_in_user():
    app = create_app(
        settings=Settings(app_secret="test-only", environment="development"),
        store=InMemoryAuthStore(),
        tenancy=TenancyStore(),
        email_sender=RecordingEmailSender(),
        broker=FakeBroker(connected=True),
    )
    client = TestClient(app, base_url=BASE_URL, follow_redirects=False)

    for path in ("/api/broker/status", "/api/broker/quote?symbol=MY.5225", "/api/broker/positions"):
        assert client.get(path).status_code == 303, path


def test_disconnected_broker_returns_a_reason_and_no_numbers(broker_env):
    broker_env.broker._connected = False
    broker_env.broker._reason = "OpenD is not listening on 127.0.0.1:11111."

    status = broker_env.client.get("/api/broker/status")
    quote = broker_env.client.get("/api/broker/quote", params={"symbol": "MY.5225"})

    assert status.status_code == 200
    assert status.json()["connected"] is False
    assert "11111" in status.json()["reason"]

    assert quote.status_code == 503
    body = quote.json()
    assert "last_price" not in body, "the refused quote carried a number anyway"
    assert "OpenD" in body["detail"]
