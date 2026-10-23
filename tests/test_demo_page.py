"""The demo dashboard: public by design, and it stays that way.

Not a build-pack criterion — a guard on the one route that deliberately serves a page to
someone with no account, so a future permission change cannot quietly close it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.broker.fake import FakeBroker
from app.config import Settings
from app.main import create_app
from app.market import MarketCache


def _client(public_dashboard: bool = True) -> TestClient:
    # A fake broker and an unstarted cache: a test must never sweep the live market.
    broker = FakeBroker()
    app = create_app(
        settings=Settings(
            app_secret="test-only",
            environment="development",
            demo_closed=not public_dashboard,
        ),
        broker=broker,
        market=MarketCache(broker),
    )
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def test_demo_page_renders_without_a_session():
    client = _client()

    response = client.get("/demo")

    assert response.status_code == 200
    body = response.text
    assert "TradeRevive AI" in body
    assert "/static/app.css" in body
    assert "/static/journal.js" in body
    # The design requirements it is meant to show, in the markup itself.
    assert "Daily P&amp;L calendar" in body
    assert "not financial advice" in body


def test_root_serves_the_dashboard_when_the_public_dashboard_is_on():
    response = _client(public_dashboard=True).get("/")

    assert response.status_code == 200
    assert "TradeRevive AI" in response.text


def test_root_sends_visitors_to_sign_in_when_the_dashboard_is_closed():
    response = _client(public_dashboard=False).get("/")

    assert response.status_code == 303
    assert response.headers["location"] == "/sign-in"


def test_static_assets_are_served():
    client = _client()

    for path in ("/static/app.css", "/static/journal.js", "/static/vendor/chart.umd.min.js"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.content, path


def test_demo_is_open_while_the_private_page_is_not():
    """The demo needs no account; /app still does."""
    client = _client()

    assert client.get("/demo").status_code == 200
    assert client.get("/app").status_code == 303
