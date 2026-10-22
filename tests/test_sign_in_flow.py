"""The sign-in page: email, then the passcode on one screen.

The development shortcut is the delicate part: it skips the emailed link so a local demo
is not blocked by a mail transport that does not exist. It must never exist outside
development, and the passcode must still be required. These tests pin both.
"""

from __future__ import annotations

import pyotp
from fastapi.testclient import TestClient

from app.auth.email import RecordingEmailSender
from app.auth.store import InMemoryAuthStore
from app.config import Settings
from app.main import create_app
from app.tenancy import TenancyStore

BASE = "https://testserver"


def _app(environment: str):
    store = InMemoryAuthStore()
    emails = RecordingEmailSender()
    app = create_app(
        settings=Settings(app_secret="test-only", environment=environment),
        store=store,
        tenancy=TenancyStore(),
        email_sender=emails,
    )
    client = TestClient(app, base_url=BASE, follow_redirects=False)
    return app, store, emails, client


def test_page_has_an_email_step_and_a_passcode_step():
    _, _, _, client = _app("development")

    page = client.get("/sign-in").text

    assert 'id="email-form"' in page
    assert 'id="code-panel"' in page
    assert "Enter your passcode" in page
    assert '/static/signin.js' in page


def test_development_shows_the_passcode_step_without_waiting_for_email():
    _, store, emails, client = _app("development")

    response = client.post("/auth/magic-link", data={"email": "dev@example.com"})

    assert response.status_code == 202
    body = response.json()
    assert body["dev_mode"] is True
    assert body["next"] == "/auth/2fa"

    # A half-session exists: the passcode is what is missing, not the link.
    gated = client.get("/app")
    assert gated.status_code == 303
    assert gated.headers["location"] == "/auth/2fa"

    # Reloading the sign-in page lands on step 2, not back on the email field.
    page = client.get("/sign-in")
    assert page.status_code == 200
    assert "started: true" in page.text

    user = store.get_user_by_email("dev@example.com")
    completed = client.post(
        "/auth/2fa", data={"code": pyotp.TOTP(user.totp_secret).now()}
    )
    assert completed.status_code == 303
    assert client.get("/app").status_code == 200


def test_development_still_requires_the_passcode():
    """Skipping the link must not skip the second factor."""
    _, _, _, client = _app("development")
    client.post("/auth/magic-link", data={"email": "nopass@example.com"})

    assert client.post("/auth/2fa", data={"code": "000000"}).status_code == 401
    assert client.get("/app").status_code == 303


def test_production_does_not_skip_the_link():
    _, _, emails, client = _app("production")

    response = client.post("/auth/magic-link", data={"email": "prod@example.com"})

    assert response.status_code == 202
    assert response.json()["dev_mode"] is False
    assert response.json()["next"] is None

    # No session: without opening the emailed link there is nothing to pass a code with.
    refused = client.get("/app")
    assert refused.status_code == 303
    assert refused.headers["location"] == "/sign-in"

    # And a real message was handed to the sender for delivery.
    assert emails.last() is not None
    assert emails.last_url()


def test_production_page_hides_the_development_banner():
    _, _, _, client = _app("production")

    page = client.get("/sign-in").text

    assert "dev: false" in page
    # The copy may exist in the markup, but only development switches it on.
    assert "dev: true" not in page
