"""The public dashboard: no sign-in, real broker data, and off unless asked for.

The risk this pins: with `PUBLIC_DASHBOARD=true`, anyone who can reach the port reads the
account's positions. So the flag defaults to off, and when it is off the route answers 404
rather than 403 — a deployment that forgot the flag must look like the feature does not
exist, not like a permission the visitor nearly had.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.broker.base import Position, Quote
from app.broker.fake import FakeBroker
from app.config import Settings
from app.main import create_app
from app.market import MarketCache

BASE = "https://testserver"


def _quote(symbol: str, last: float, rate: float) -> Quote:
    return Quote(
        symbol=symbol,
        name="Test Instrument",
        last_price=last,
        previous_close=last / (1 + rate / 100),
        change_rate=rate,
        volume=1_234_500,
        bid=last - 0.05,
        ask=last + 0.05,
        updated_at="2026-10-22T09:00:00",
        delayed=False,
        source="fake",
    )


def _client(
    *,
    public: bool,
    broker: FakeBroker | None = None,
    watchlist: str = "US.AAPL,HK.00700",
) -> TestClient:
    broker = broker or FakeBroker(
        quotes={"US.AAPL": _quote("US.AAPL", 343.99, 1.32), "HK.00700": _quote("HK.00700", 380.0, -3.56)},
        positions=[
            Position(
                symbol="US.AAPL",
                name="Apple Inc",
                quantity=10,
                cost_price=300.0,
                market_price=343.99,
                market_value=3439.9,
                unrealised_pl=439.9,
            )
        ],
    )
    app = create_app(
        settings=Settings(
            app_secret="test-only",
            environment="development",
            public_dashboard=public,
            demo_watchlist=watchlist,
        ),
        broker=broker,
        # Never start the sweep thread in a test: the cache is exercised directly.
        market=MarketCache(broker),
    )
    return TestClient(app, base_url=BASE, follow_redirects=False)


def test_market_route_is_closed_unless_the_flag_is_on():
    response = _client(public=False).get("/api/public/market")

    assert response.status_code == 404


def test_market_route_returns_real_quotes_and_positions():
    response = _client(public=True).get("/api/public/market")

    assert response.status_code == 200
    body = response.json()
    assert body["broker"]["connected"] is True
    assert [q["symbol"] for q in body["quotes"]] == ["US.AAPL", "HK.00700"]
    assert body["quotes"][0]["last_price"] == 343.99
    assert body["quotes"][0]["change_rate"] == 1.32
    assert body["positions"][0]["unrealised_pl"] == 439.9
    assert body["positions_error"] is None


def test_one_symbol_without_permission_does_not_blank_the_strip():
    """A missing entitlement is reported per symbol; the rest still render."""
    broker = FakeBroker(quotes={"US.AAPL": _quote("US.AAPL", 343.99, 1.32)})

    body = _client(public=True, broker=broker).get("/api/public/market").json()

    assert body["quotes"][0]["last_price"] == 343.99
    assert "error" in body["quotes"][1]
    assert body["quotes"][1]["symbol"] == "HK.00700"


def test_disconnected_broker_reports_a_reason_and_no_prices():
    broker = FakeBroker(connected=False, reason="OpenD is not listening on 127.0.0.1:11111")

    body = _client(public=True, broker=broker).get("/api/public/market").json()

    assert body["broker"]["connected"] is False
    assert "11111" in body["broker"]["reason"]
    # No invented numbers anywhere.
    assert all("last_price" not in q for q in body["quotes"])
    assert body["positions"] == []


def test_dashboard_is_the_front_door_when_the_flag_is_on():
    response = _client(public=True).get("/")

    assert response.status_code == 200
    body = response.text
    assert "US market" in body
    assert 'id="chart-dist"' in body
    assert 'id="screen-body"' in body
    assert "/static/market.js" in body


def test_journal_page_carries_the_performance_work():
    response = _client(public=True).get("/journal")

    assert response.status_code == 200
    body = response.text
    assert "Equity curve" in body
    assert "Daily P&amp;L calendar" in body
    assert "Mistake breakdown" in body
    assert "/static/journal.js" in body


def test_journal_page_stays_private_with_the_dashboard_off():
    response = _client(public=False).get("/journal")

    assert response.status_code == 303
    assert response.headers["location"] == "/sign-in"


def test_the_market_page_does_not_promise_advice():
    """The screen must never read like a buy signal."""
    body = _client(public=True).get("/").text.lower()

    assert "not a recommendation" in body
    assert "does not tell you what to buy" in body


def test_front_door_sends_visitors_to_sign_in_when_the_dashboard_is_private():
    response = _client(public=False).get("/")

    assert response.status_code == 303
    assert response.headers["location"] == "/sign-in"


def test_positions_stay_behind_the_login_when_the_dashboard_is_private():
    """The private broker API is unaffected by the public flag."""
    client = _client(public=False)

    response = client.get("/api/broker/positions")

    assert response.status_code == 303
    assert response.headers["location"] == "/sign-in"
    assert "position" not in response.text.lower()


def test_diagnosis_page_embeds_the_flowise_chatflow():
    response = _client(public=True).get("/diagnosis")

    assert response.status_code == 200
    body = response.text
    # The chatflow id is public by design; a secret here would be the failure.
    assert "flowise-embed" in body
    assert "f2ac3baa-63d0-4ce2-ba69-07d8fa7b66c8" in body
    assert "https://flowise.bdctraining.cloud" in body
    assert "apiKey" not in body


def test_diagnosis_page_stays_private_with_the_dashboard_off():
    response = _client(public=False).get("/diagnosis")

    assert response.status_code == 303
    assert response.headers["location"] == "/sign-in"
