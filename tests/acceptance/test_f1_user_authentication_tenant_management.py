"""Acceptance tests: User Authentication & Tenant Management (use case UC1 in docs/REQUIREMENTS.md)

Used by: Trader (Account Owner). Allows traders to register, log in, manage profiles, select UI language (EN/BM), and secure their data.

Filled in at M3. Registration is magic-link based (docs/AUTH.md, AGENTS.md: no password is
ever stored), so "compliant password" is satisfied by the flow having no password at all.

AC1.2 asks for a clear "email already in use" answer, which does disclose that an address
is registered. That is the pack's choice here; the sign-in endpoint itself still answers
202 for everyone.
"""

import pytest


def test_ac1_1(pg_env):
    """A new address creates a user with its own tenant_id, 201, and a confirmation email."""
    response = pg_env.register("new@example.com", "New Trader")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user_id"]
    assert body["tenant_id"].startswith("tenant_")

    user = pg_env.store.get_user_by_email("new@example.com")
    assert user is not None
    assert user.tenant_id == body["tenant_id"]
    assert user.password_hash is None and user.totp_secret is None

    # An email confirmation trigger: a message went out, and it carries a link.
    message = pg_env.emails.last()
    assert message is not None, "registration sent no email"
    assert message.to == "new@example.com"
    assert pg_env.emails.last_url(), "the confirmation email carried no link"


def test_ac1_2(pg_env):
    """A second registration with the same address is rejected with a clear message."""
    first = pg_env.register("taken@example.com", "First")
    assert first.status_code == 201

    second = pg_env.register("taken@example.com", "Second")

    assert second.status_code == 409, second.text
    assert "already" in second.json()["detail"].lower()
    assert "taken@example.com" in second.json()["detail"]

    # And it did not create a second account.
    assert len(pg_env.store.users_with_email("taken@example.com")) == 1


def test_ac1_3(pg_env):
    """A signed-in owner asking for another tenant's data is refused with 403."""
    pg_env.sign_in("owner@example.com")
    other = pg_env.register("other@example.com", "Other")
    other_tenant = other.json()["tenant_id"]

    assert other_tenant != pg_env.store.get_user_by_email("owner@example.com").tenant_id

    response = pg_env.client.get("/export", params={"tenant_id": other_tenant})

    assert response.status_code == 403, response.text
    assert other_tenant not in response.text


def test_ac1_4(pg_env):
    """Switching to Bahasa Melayu relabels the UI, deterministically and without a model."""
    pg_env.sign_in("bm@example.com")

    before = pg_env.client.get("/app")
    assert before.status_code == 200
    assert "Your workspace" in before.text

    changed = pg_env.client.patch("/account/language", json={"language": "ms"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["language"] == "ms"

    after = pg_env.client.get("/app")
    assert after.status_code == 200
    assert "Ruang kerja anda" in after.text, "labels did not switch to Bahasa Melayu"
    assert "Your workspace" not in after.text

    # No model was invoked: the app has no AI client at all in M1–M3, and no key is
    # configured, so a translation that exists can only have come from the dictionary.
    key = pg_env.app.state.settings.deepseek_api_key
    assert key is None or key.get_secret_value() == "", "an AI key is configured"
    assert not hasattr(pg_env.app.state, "ai"), "an AI client exists on the app already"


def test_ac1_bad_language_is_rejected(pg_env):
    """The language preference accepts only the two languages the product ships."""
    pg_env.sign_in("lang@example.com")
    response = pg_env.client.patch("/account/language", json={"language": "kl"})
    assert response.status_code == 400
