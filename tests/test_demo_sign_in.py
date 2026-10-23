"""Demo sign-in: a way into a hosted copy that has no mail provider.

There is no SMTP or API email sender wired, so a deployed copy cannot deliver a magic link.
Without this route the app is unusable on a host — which is exactly what happened.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.broker.fake import FakeBroker
from app.config import Settings
from app.main import create_app
from app.market import MarketCache


def _client(
    demo_sign_in: bool = True,
    environment: str = "development",
    require_sign_in: bool = True,
) -> TestClient:
    broker = FakeBroker()
    app = create_app(
        settings=Settings(
            app_secret="test-only",
            environment=environment,
            demo_sign_in=demo_sign_in,
            require_sign_in=require_sign_in,
        ),
        broker=broker,
        market=MarketCache(broker),
    )
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def test_demo_sign_in_opens_the_workspace_without_email():
    client = _client()

    response = client.post("/auth/demo")

    assert response.status_code == 303
    assert response.headers["location"] == "/app"
    # The session is complete: no passcode step in the way.
    assert client.get("/app").status_code == 200


def test_demo_sign_in_also_works_outside_development():
    """A hosted copy usually runs with ENVIRONMENT unset or production."""
    client = _client(environment="production")

    assert client.post("/auth/demo").status_code == 303
    assert client.get("/app").status_code == 200


def test_it_can_be_switched_off():
    client = _client(demo_sign_in=False)

    assert client.post("/auth/demo").status_code == 404
    assert client.get("/app").status_code == 303


def test_the_button_only_appears_when_the_route_is_live():
    with_button = _client().get("/sign-in").text
    without_button = _client(demo_sign_in=False).get("/sign-in").text

    assert "demo-form" in with_button
    assert '"demo": true' in with_button or "demo: true" in with_button
    assert "demo: false" in without_button


def test_the_same_account_is_reused_across_sign_ins():
    client = _client()
    client.post("/auth/demo")
    tenant_first = client.get("/app").text.split('data-tenant="')[1].split('"')[0]

    client.post("/auth/sign-out")
    client.post("/auth/demo")
    tenant_second = client.get("/app").text.split('data-tenant="')[1].split('"')[0]

    assert tenant_first == tenant_second


# ------------------------------------------------------- no login page at all


def test_with_sign_in_off_the_workspace_is_the_entry_point():
    """REQUIRE_SIGN_IN=false: no login page, /app just opens."""
    client = _client(require_sign_in=False)

    assert client.get("/app").status_code == 200
    # And the login page is not a page any more: it goes into the workspace.
    response = client.get("/sign-in")
    assert response.status_code == 303
    assert response.headers["location"] == "/app"


def test_with_sign_in_off_the_visitor_is_the_demo_account():
    client = _client(require_sign_in=False)

    first = client.get("/app").text.split('data-tenant="')[1].split('"')[0]
    other = _client(require_sign_in=False).get("/app").text.split('data-tenant="')[1].split('"')[0]

    assert first == other


def test_with_sign_in_on_the_login_page_still_guards_the_workspace():
    client = _client(require_sign_in=True)

    refused = client.get("/app")

    assert refused.status_code == 303
    assert refused.headers["location"] == "/sign-in"
    assert client.get("/sign-in").status_code == 200
