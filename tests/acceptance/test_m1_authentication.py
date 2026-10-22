"""Acceptance tests: M1 · Authentication (docs/BUILD_PLAN.md, docs/AUTH.md).

The build pack's eight criteria, one test each:

1. A signed-out request to a private page is refused
2. Sign-in and sign-out work in the provider's test mode
3. No password is stored in plain text, and no session token appears in a log
4. Sign-in works with: Email magic link
5. Sign-in works with: Google sign-in
6. An unverified email address cannot use the app
7. Repeated failed sign-ins are slowed down, then locked for a while
8. An owner or admin must pass two-factor sign-in

Plus one test the milestone goal implies and no criterion covers: a session belonging to
one tenant cannot read another tenant's page (the hook M2's matrix builds on).

"Provider's test mode" here means an injected fake provider: tests never touch Google.
The real Authlib Google client is wired in `app/auth/google.py` and needs
GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET at runtime, which tests must not require.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pyotp
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.auth.email import RecordingEmailSender
from app.auth.google import FakeGoogleProvider, GoogleIdentity
from app.auth.store import InMemoryAuthStore
from app.auth.throttle import LOCK_AFTER_FAILURES, LOCK_SECONDS
from app.config import Settings
from app.main import create_app

BASE_URL = "https://testserver"
SESSION_COOKIE = "tr_session"
TRADER = "Trader (Account Owner)"
ADMIN = "System Administrator"
MFA_ROLES = (TRADER, ADMIN)


class FakeClock:
    """A clock the test moves by hand, so a 15-minute lock takes no real time."""

    def __init__(self) -> None:
        self._now = datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


@pytest.fixture
def env():
    """An app wired to fakes: no Google, no SMTP, no real clock."""
    store = InMemoryAuthStore()
    emails = RecordingEmailSender()
    google = FakeGoogleProvider(
        identity=GoogleIdentity(
            subject="google-123",
            email="trader@example.com",
            email_verified=True,
            name="Aisyah Trader",
        )
    )
    clock = FakeClock()
    app = create_app(
        settings=Settings(app_secret=SecretStr("test-only-session-secret")),
        store=store,
        email_sender=emails,
        google=google,
        clock=clock.now,
    )
    client = TestClient(app, base_url=BASE_URL, follow_redirects=False)
    return SimpleNamespace(
        app=app, client=client, store=store, emails=emails, google=google, clock=clock
    )


# --------------------------------------------------------------------------- helpers


def _link_from_emails(emails: RecordingEmailSender) -> str:
    url = emails.last_url()
    assert url, "the magic-link email contained no link"
    return url


def start_magic_link(client: TestClient, emails: RecordingEmailSender, email: str) -> str:
    """Ask for a magic link; return the URL the email carried."""
    response = client.post("/auth/magic-link", data={"email": email})
    assert response.status_code == 202, response.text
    url = _link_from_emails(emails)
    emails.clear()
    return url


def follow_magic_link(client: TestClient, emails: RecordingEmailSender, email: str) -> None:
    url = start_magic_link(client, emails, email)
    response = client.get(urlsplit(url).path)
    assert response.status_code == 303, response.text


def sign_in_with_google(client: TestClient) -> object:
    """Walk the fake provider's round trip, including the state check."""
    start = client.get("/auth/google")
    assert start.status_code == 303, start.text
    location = start.headers["location"]
    state = parse_qs(urlsplit(location).query)["state"][0]
    return client.get(
        "/auth/google/callback", params={"code": "test-code", "state": state}
    )


def totp_for(store: InMemoryAuthStore, email: str) -> str:
    user = store.get_user_by_email(email)
    assert user is not None, f"no user for {email}"
    assert user.totp_secret, "the user has no TOTP secret to enrol with"
    return pyotp.TOTP(user.totp_secret).now()


def pass_two_factor(env, email: str = "trader@example.com") -> None:
    response = env.client.post("/auth/2fa", data={"code": totp_for(env.store, email)})
    assert response.status_code == 303, response.text


def sign_in_fully(env, client: TestClient | None = None, email: str = "trader@example.com") -> None:
    client = client or env.client
    follow_magic_link(client, env.emails, email)
    code = totp_for(env.store, email)
    response = client.post("/auth/2fa", data={"code": code})
    assert response.status_code == 303, response.text


# ------------------------------------------------------------------- the criteria


def test_ac_m1_signed_out_request_to_private_page_is_refused(env):
    """Criterion 1: no session means no private page."""
    response = env.client.get("/app")

    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/sign-in"


def test_ac_m1_sign_in_and_sign_out_work_in_provider_test_mode(env):
    """Criterion 2: in, out, and back to refused, against the fake provider."""
    callback = sign_in_with_google(env.client)
    assert callback.status_code == 303, callback.text

    gated = env.client.get("/app")
    assert gated.status_code == 303
    assert gated.headers["location"] == "/auth/2fa", "2FA must gate the session"

    pass_two_factor(env)
    assert env.client.get("/app").status_code == 200

    signed_out = env.client.post("/auth/sign-out")
    assert signed_out.status_code == 303
    assert env.client.get("/app").status_code == 303


def test_ac_m1_no_password_stored_and_no_session_token_in_log(env, caplog):
    """Criterion 3: nothing password-shaped is written, no token reaches a log line."""
    with caplog.at_level(logging.DEBUG):
        sign_in_fully(env)
        assert env.client.get("/app").status_code == 200

    user = env.store.get_user_by_email("trader@example.com")
    stored = asdict(user)
    assert stored["password_hash"] is None, "a password value was persisted"
    assert not [
        key for key, value in stored.items() if "password" in key.lower() and value
    ], "a password-shaped field holds a value"

    session_value = env.client.cookies.get(SESSION_COOKIE)
    assert session_value, "no session cookie was issued"

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert session_value not in logged, "the session cookie value reached a log line"
    assert session_value.split(".")[0] not in logged, "the signed session payload reached a log"
    assert "trader@example.com" not in logged, "personal data reached a log line"

    # The check above is only meaningful if the app logged something at all.
    assert any(
        record.name.startswith("app") for record in caplog.records
    ), "the app emitted no log line, so the no-token check proved nothing"


def test_ac_m1_sign_in_works_with_email_magic_link(env):
    """Criterion 4: a link from the email signs you in, once."""
    url = start_magic_link(env.client, env.emails, "trader@example.com")
    path = urlsplit(url).path

    first = env.client.get(path)
    assert first.status_code == 303, first.text

    user = env.store.get_user_by_email("trader@example.com")
    assert user is not None
    assert user.provider == "magic_link"
    assert user.email_verified is True, "following the link is the verification"
    assert user.tenant_id, "sign-up must establish a tenant workspace"

    pass_two_factor(env)
    assert env.client.get("/app").status_code == 200

    # Single use: the same link cannot be replayed.
    replay = TestClient(env.app, base_url=BASE_URL, follow_redirects=False)
    assert replay.get(path).status_code in (400, 401, 403)


def test_ac_m1_sign_in_works_with_google(env):
    """Criterion 5: the Google round trip creates the account and its tenant."""
    callback = sign_in_with_google(env.client)
    assert callback.status_code == 303, callback.text

    user = env.store.get_user_by_email("trader@example.com")
    assert user is not None
    assert user.provider == "google"
    assert user.tenant_id

    pass_two_factor(env)
    assert env.client.get("/app").status_code == 200


def test_ac_m1_unverified_email_cannot_use_the_app(env):
    """Criterion 6: Google says the address is unverified, so the door stays shut."""
    env.google.identity = GoogleIdentity(
        subject="google-999",
        email="unverified@example.com",
        email_verified=False,
        name="Unverified Person",
    )

    callback = sign_in_with_google(env.client)

    assert callback.status_code == 403, callback.text
    assert env.client.get("/app").status_code == 303, "an unverified address got a session"
    assert (
        env.store.get_user_by_email("unverified@example.com") is None
    ), "an unverified account was created"


def test_ac_m1_repeated_failed_sign_ins_are_slowed_then_locked(env):
    """Criterion 7: wrong codes slow down, then lock, and a right code waits too."""
    follow_magic_link(env.client, env.emails, "trader@example.com")

    for attempt in range(1, LOCK_AFTER_FAILURES + 1):
        response = env.client.post("/auth/2fa", data={"code": "000000"})
        if attempt < 4:
            assert response.status_code == 401, f"attempt {attempt}: {response.text}"
        elif attempt < LOCK_AFTER_FAILURES:
            assert response.status_code == 429, f"attempt {attempt} was not slowed down"
            assert int(response.headers["retry-after"]) >= 1
        else:
            assert response.status_code == 429, "the account was never locked"
            assert int(response.headers["retry-after"]) == LOCK_SECONDS

    # Locked means locked: the correct code is refused while the lock holds.
    still_locked = env.client.post(
        "/auth/2fa", data={"code": totp_for(env.store, "trader@example.com")}
    )
    assert still_locked.status_code == 429

    env.clock.advance(LOCK_SECONDS + 1)

    recovered = env.client.post(
        "/auth/2fa", data={"code": totp_for(env.store, "trader@example.com")}
    )
    assert recovered.status_code == 303, "the lock did not lift after its window"


def test_ac_m1_owner_or_admin_must_pass_two_factor(env):
    """Criterion 8: a magic link alone is not enough for an Account Owner."""
    follow_magic_link(env.client, env.emails, "trader@example.com")

    user = env.store.get_user_by_email("trader@example.com")
    assert user.role in MFA_ROLES

    gated = env.client.get("/app")
    assert gated.status_code == 303
    assert gated.headers["location"] == "/auth/2fa"

    # A wrong code changes nothing.
    assert env.client.post("/auth/2fa", data={"code": "123456"}).status_code == 401
    assert env.client.get("/app").status_code == 303

    pass_two_factor(env)
    assert env.client.get("/app").status_code == 200


def test_ac_m1_one_tenants_session_cannot_read_another_tenants_page(env):
    """Addition: the tenant on the session, not on the client, decides what is visible."""
    first = TestClient(env.app, base_url=BASE_URL, follow_redirects=False)
    follow_magic_link(first, env.emails, "aisyah@example.com")
    first.post("/auth/2fa", data={"code": totp_for(env.store, "aisyah@example.com")})

    second = TestClient(env.app, base_url=BASE_URL, follow_redirects=False)
    follow_magic_link(second, env.emails, "bala@example.com")
    second.post("/auth/2fa", data={"code": totp_for(env.store, "bala@example.com")})

    aisyah = env.store.get_user_by_email("aisyah@example.com")
    bala = env.store.get_user_by_email("bala@example.com")
    assert aisyah.tenant_id != bala.tenant_id, "each sign-up must get its own tenant"

    aisyah_page = first.get("/app")
    bala_page = second.get("/app")
    assert aisyah_page.status_code == 200 and bala_page.status_code == 200
    assert aisyah.tenant_id in aisyah_page.text
    assert aisyah.tenant_id not in bala_page.text, "one tenant saw another's id"
