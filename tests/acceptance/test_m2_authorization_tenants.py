"""Acceptance tests: M2 · Authorization and tenants (docs/AUTH.md, docs/DATA_MODEL.md).

The build pack's four criteria:

1. Customer A cannot read or change customer B's records, on every table
2. A route with no permission rule is refused
3. Only a role allowed to manage the team can change a role
4. A Guest / Anonymous Visitor is refused: User Authentication & Tenant Management,
   Manage team and roles, AI settings, Usage and logs, Export data

Plus two the goal implies: the matrix in code must equal the matrix in blueprint.json
(otherwise "checks the role against the permission matrix" is unverifiable), and an
unknown role must be denied everything.

Note on criterion 4: the blueprint's matrix *grants* Guest seven permissions, including
trade import and AI diagnostics. That is implemented as written and reported as a pack
defect; `test_guest_permissions_follow_the_matrix_exactly` pins that behaviour so a
future pack change is visible here.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pyotp
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.auth.email import RecordingEmailSender
from app.auth.google import FakeGoogleProvider, GoogleIdentity
from app.auth.store import InMemoryAuthStore
from app.config import Settings
from app.main import create_app
from app.permissions import ADMIN, GUEST, MATRIX, TRADER, role_has
from app.tenancy import TABLES, RecordNotFound, TenancyStore

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://testserver"

# The five permissions the build pack names for criterion 4.
GUEST_REFUSED = (
    "f:User Authentication & Tenant Management",
    "team",
    "ai",
    "usage",
    "export",
)


@pytest.fixture
def env():
    auth = InMemoryAuthStore()
    tenancy = TenancyStore()
    emails = RecordingEmailSender()
    app = create_app(
        settings=Settings(app_secret=SecretStr("test-only-session-secret")),
        store=auth,
        email_sender=emails,
        google=FakeGoogleProvider(
            identity=GoogleIdentity(
                subject="g-1", email="trader@example.com", email_verified=True, name="A"
            )
        ),
        tenancy=tenancy,
    )
    return SimpleNamespace(
        app=app,
        auth=auth,
        tenancy=tenancy,
        emails=emails,
        client=TestClient(app, base_url=BASE_URL, follow_redirects=False),
        new_client=lambda: TestClient(app, base_url=BASE_URL, follow_redirects=False),
    )


def sign_in(env, client: TestClient, email: str):
    """Magic link + second factor, i.e. a fully signed-in account owner."""
    requested = client.post("/auth/magic-link", data={"email": email})
    assert requested.status_code == 202, requested.text
    url = env.emails.last_url()
    assert url, "no magic link was recorded"
    env.emails.clear()
    assert client.get(urlsplit(url).path).status_code == 303
    user = env.auth.get_user_by_email(email)
    code = pyotp.TOTP(user.totp_secret).now()
    assert client.post("/auth/2fa", data={"code": code}).status_code == 303
    return user


# ---------------------------------------------------------------- criterion 1


def test_cannot_read_or_change_another_tenants_records_on_every_table(env):
    """Criterion 1: same enforcement on all six tables, and no way to ask for another tenant."""
    a = sign_in(env, env.client, "a@example.com")
    b = sign_in(env, env.new_client(), "b@example.com")
    a_scope = env.tenancy.scope(a.tenant_id)
    b_scope = env.tenancy.scope(b.tenant_id)

    for table in TABLES:
        a_row = a_scope.add(table, symbol="AAA")
        b_row = b_scope.add(table, symbol="BBB")

        with pytest.raises(RecordNotFound, match=table):
            a_scope.get(table, b_row["id"])
        with pytest.raises(RecordNotFound, match=table):
            a_scope.update(table, b_row["id"], symbol="HACKED")
        with pytest.raises(RecordNotFound, match=table):
            a_scope.delete(table, b_row["id"])

        assert b_scope.get(table, b_row["id"])["symbol"] == "BBB", "B's row was changed"
        a_ids = [row["id"] for row in a_scope.list(table)]
        assert a_row["id"] in a_ids
        assert b_row["id"] not in a_ids, f"{table}: a list leaked another tenant's row"

        # The tenant is taken from the signed-in user, never from the row or the caller.
        smuggled = a_scope.add(table, tenant_id=b.tenant_id, symbol="SMUGGLED")
        assert smuggled["tenant_id"] == a.tenant_id, f"{table}: tenant_id was overridable"

    # AC1.3 (M3) made this stricter than the M2 version of this test: a tenant_id that is
    # not the caller's is now refused outright rather than quietly ignored.
    smuggled = env.client.get("/export", params={"tenant_id": b.tenant_id})
    assert smuggled.status_code == 403, smuggled.text
    assert b.tenant_id not in smuggled.text

    exported = env.client.get("/export")
    assert exported.status_code == 200, exported.text
    assert exported.json()["tenant_id"] == a.tenant_id, "the export was not scoped to A"


def test_every_table_in_the_data_model_is_scoped(env):
    """The table list is the doc's list, so 'every table' cannot silently shrink."""
    headings = re.findall(r"^## (\w+)$", (ROOT / "docs" / "DATA_MODEL.md").read_text("utf-8"), re.M)
    documented = tuple(name for name in headings if name in TABLES)
    assert set(documented) == set(TABLES), (
        f"DATA_MODEL.md documents {sorted(documented)}, code scopes {sorted(TABLES)}"
    )


# ---------------------------------------------------------------- criterion 2


def test_route_with_no_permission_rule_is_refused(env):
    """Criterion 2: an undeclared route is refused even for a fully signed-in owner."""
    sign_in(env, env.client, "owner@example.com")

    undeclared = env.client.get("/internal/debug")
    assert undeclared.status_code == 403, undeclared.text
    assert "no permission rule" in undeclared.text.lower()

    # A declared route still answers, so the refusal above is about the rule and not
    # about the app refusing everything.
    assert env.client.get("/account").status_code == 200


# ---------------------------------------------------------------- criterion 3


def test_only_a_role_allowed_to_manage_the_team_can_change_a_role(env):
    """Criterion 3: the team permission decides, and an unknown role gets nothing."""
    owner = sign_in(env, env.client, "owner@example.com")
    member = env.auth.upsert_user(
        email="member@example.com", name="Member", provider="magic_link", email_verified=True
    )
    env.auth.save_user(member)
    assert member.tenant_id != owner.tenant_id

    # Anonymous: refused by the matrix (Guest has no "team").
    anonymous = env.new_client()
    assert anonymous.post(
        "/team/roles", json={"user_id": owner.id, "role": ADMIN}
    ).status_code == 403

    # Account Owner has "team", so it may change a role inside its own tenant.
    allowed = env.client.post("/team/roles", json={"user_id": owner.id, "role": ADMIN})
    assert allowed.status_code == 200, allowed.text
    assert env.auth.get_user(owner.id).role == ADMIN

    # Another tenant's user is not reachable, permission or not.
    cross = env.client.post("/team/roles", json={"user_id": member.id, "role": ADMIN})
    assert cross.status_code == 404, cross.text

    # A role the matrix does not list is denied even though it is signed in.
    env.auth.save_user(_with_role(env.auth.get_user(owner.id), "Read-Only Analyst"))
    denied = env.client.post("/team/roles", json={"user_id": owner.id, "role": TRADER})
    assert denied.status_code == 403, denied.text


def _with_role(user, role):
    user.role = role
    return user


# ---------------------------------------------------------------- criterion 4


def test_guest_is_refused_the_five_named_permissions(env):
    """Criterion 4: an anonymous visitor is refused exactly these five."""
    guest = env.new_client()

    routes = {
        "f:User Authentication & Tenant Management": "/account",
        "team": "/team/roles",
        "ai": "/admin/ai-settings",
        "usage": "/admin/usage",
        "export": "/export",
    }
    for permission, path in routes.items():
        response = guest.get(path)
        assert response.status_code in (403, 303), f"{path} was not refused: {response.status_code}"
        assert response.status_code == 403, (
            f"{path} ({permission}) let an anonymous visitor through"
        )

    # Not a blanket refusal: the matrix grants Guest business settings.
    assert guest.get("/settings").status_code == 200


def test_guest_permissions_follow_the_matrix_exactly(env):
    """Pins the blueprint's Guest grants, including the ones that look unsafe.

    The blueprint gives Guest trade import, the analytics engine, the mistake detector,
    the AI report, the dashboard, billing and settings. This test records that as the
    implemented behaviour so that (a) the app matches the source of truth and (b) a
    corrected pack shows up here as a deliberate change.
    """
    granted = MATRIX[GUEST]
    assert "f:Trade Data Import & Ingestion" in granted
    assert "f:AI Trading Diagnosis & Recovery Report" in granted
    for refused in GUEST_REFUSED:
        assert refused not in granted


# ------------------------------------------------------- matrix drift + unknown


def test_permission_matrix_matches_blueprint():
    """The code's matrix and blueprint.json's matrix must agree cell for cell."""
    blueprint = json.loads((ROOT / "blueprint.json").read_text("utf-8"))
    authorization = blueprint["core"]["authorization"]
    expected = {role: set(permissions) for role, permissions in authorization["matrix"].items()}

    assert set(expected) == set(MATRIX), "the roles in code differ from the blueprint's roles"
    for role, permissions in expected.items():
        assert MATRIX[role] == permissions, (
            f"{role}: code and blueprint disagree on "
            f"{sorted(MATRIX[role] ^ permissions)}"
        )
    # Every permission listed by the blueprint must be known to the code.
    known = {item["id"] for item in authorization["permissions"]}
    used = set().union(*MATRIX.values())
    assert used <= known, f"the matrix grants permissions the blueprint never declares: {used - known}"


def test_unknown_role_is_denied_everything():
    for role in ("", "root", "Read-Only Analyst", None):
        for permission in MATRIX[TRADER]:
            assert role_has(role, permission) is False


def test_every_registered_route_declares_a_permission(env):
    """No route may reach a handler without a rule — the canary is the only exception."""
    from fastapi.routing import APIRoute

    from app.permissions import PERMISSION_ATTR
    from app.routes import admin as admin_routes
    from app.routes import auth as auth_routes
    from app.routes import pages as page_routes

    endpoints: list[APIRoute] = []
    for router in (auth_routes.router, page_routes.router, admin_routes.router):
        assert router.routes, "a router registered no routes"
        endpoints.extend(route for route in router.routes if isinstance(route, APIRoute))
    endpoints.extend(route for route in env.app.routes if isinstance(route, APIRoute))

    assert len(endpoints) >= 17, f"only found {len(endpoints)} routes to check"
    undeclared = sorted(
        {
            route.path
            for route in endpoints
            if getattr(route.endpoint, PERMISSION_ATTR, None) is None
        }
    )
    assert undeclared == ["/internal/debug"], (
        "these routes have no @permit/@public marker and would be refused at runtime: "
        f"{undeclared}"
    )


def test_api_docs_are_off_outside_development():
    """The OpenAPI schema is not a guarded route, so it must not exist in production."""
    production = create_app(
        settings=Settings(app_secret=SecretStr("x"), environment="production")
    )
    client = TestClient(production, base_url=BASE_URL, follow_redirects=False)
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404

    development = create_app(
        settings=Settings(app_secret=SecretStr("x"), environment="development")
    )
    assert TestClient(development, base_url=BASE_URL).get("/docs").status_code == 200
