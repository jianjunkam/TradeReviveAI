"""Roles, the permission matrix, and the deny-by-default route guard.

The matrix is blueprint.json's `core.authorization.matrix`, spelled out here as code.
`tests/acceptance/test_m2_authorization_tenants.py` parses the blueprint and fails if the
two ever disagree, so this file cannot drift from the source of truth.

Deny by default has two teeth:
  * a route with no `@permit(...)` or `@public` marker is refused, and
  * a role the matrix does not list has no permissions at all.
"""

from __future__ import annotations

from typing import Callable, Final

from fastapi import HTTPException, Request

from app.auth import sessions
from app.auth.demo import ensure_demo_session
from app.auth.store import ADMIN, GUEST, TRADER

__all__ = [
    "ADMIN",
    "GUEST",
    "MATRIX",
    "PUBLIC",
    "ROLES",
    "TRADER",
    "guard",
    "permit",
    "public",
    "role_has",
]

ROLES: Final = (TRADER, GUEST, ADMIN)

# Permission ids exactly as blueprint.json spells them.
F_AUTH: Final = "f:User Authentication & Tenant Management"
F_IMPORT: Final = "f:Trade Data Import & Ingestion"
F_ANALYTICS: Final = "f:Quantitative Performance Analytics Engine"
F_MISTAKES: Final = "f:Rule-Based Behavioral Mistake Detector"
F_REPORT: Final = "f:AI Trading Diagnosis & Recovery Report"
F_DASHBOARD: Final = "f:Interactive Performance Dashboard"
F_RISK: Final = "f:Risk Management & Position Size Calculator"
F_LANGUAGE: Final = "f:Multi-Language Support (EN & BM)"
F_MENTOR: Final = "f:Interactive AI Trading Mentor (Chatbot)"
F_WHATIF: Final = "f:What-If Strategy Simulator"
F_SIGNALS: Final = "f:Live Buy/Sell Trading Signals"
P_TEAM: Final = "team"
P_BILLING: Final = "billing"
P_SETTINGS: Final = "settings"
P_AI: Final = "ai"
P_USAGE: Final = "usage"
P_EXPORT: Final = "export"

MATRIX: Final[dict[str, frozenset[str]]] = {
    TRADER: frozenset(
        {
            F_AUTH,
            F_IMPORT,
            F_ANALYTICS,
            F_MISTAKES,
            F_REPORT,
            F_DASHBOARD,
            F_RISK,
            F_LANGUAGE,
            F_MENTOR,
            F_WHATIF,
            F_SIGNALS,
            P_TEAM,
            P_BILLING,
            P_SETTINGS,
            P_AI,
            P_USAGE,
            P_EXPORT,
        }
    ),
    # The build pack grants Guest twelve permissions, including trade import and the AI
    # report. Implemented as written; flagged to the human as a pack defect.
    GUEST: frozenset(
        {
            F_IMPORT,
            F_ANALYTICS,
            F_MISTAKES,
            F_REPORT,
            F_DASHBOARD,
            F_RISK,
            F_LANGUAGE,
            F_MENTOR,
            F_WHATIF,
            F_SIGNALS,
            P_BILLING,
            P_SETTINGS,
        }
    ),
    ADMIN: frozenset(
        {
            F_AUTH,
            F_IMPORT,
            F_ANALYTICS,
            F_MISTAKES,
            F_REPORT,
            F_DASHBOARD,
            F_RISK,
            F_LANGUAGE,
            F_MENTOR,
            F_WHATIF,
            F_SIGNALS,
            P_TEAM,
            P_BILLING,
            P_SETTINGS,
            P_AI,
            P_USAGE,
            P_EXPORT,
        }
    ),
}

#: Marker for a route that deliberately needs no permission (sign-in, health).
PUBLIC: Final = "__public__"

PERMISSION_ATTR = "__permission__"
SIGN_IN_REQUIRED_ATTR = "__sign_in_required__"


def role_has(role: str | None, permission: str) -> bool:
    """Deny by default: an unknown or missing role holds no permissions."""
    if not role:
        return False
    return permission in MATRIX.get(role, frozenset())


def permit(permission: str, *, sign_in_required: bool = False) -> Callable:
    """Declare what a route needs. Without one of these, the guard refuses it.

    `sign_in_required` only changes *how* an anonymous request is refused: a redirect to
    /sign-in for pages, a plain 403 for everything else.
    """

    def decorate(endpoint: Callable) -> Callable:
        setattr(endpoint, PERMISSION_ATTR, permission)
        setattr(endpoint, SIGN_IN_REQUIRED_ATTR, sign_in_required)
        return endpoint

    return decorate


def public(endpoint: Callable) -> Callable:
    """A declared public route: no session, no permission, on purpose."""
    setattr(endpoint, PERMISSION_ATTR, PUBLIC)
    setattr(endpoint, SIGN_IN_REQUIRED_ATTR, False)
    return endpoint


def guard(request: Request) -> None:
    """The dependency every router runs: deny by default, then check the matrix."""
    endpoint = getattr(request.scope.get("route"), "endpoint", None)
    declared = getattr(endpoint, PERMISSION_ATTR, None)

    if declared is None:
        raise HTTPException(
            status_code=403,
            detail="This route has no permission rule, so it is refused.",
        )
    if declared is PUBLIC:
        return

    # No login page on a demo deployment: every visitor is the one demo account, so routes
    # that require a signed-in user behave as if someone had signed in.
    settings = getattr(request.app.state, "settings", None)
    if settings is not None and not getattr(settings, "require_sign_in", True):
        ensure_demo_session(request)

    user = sessions.current_user(request)
    if user is None:
        if getattr(endpoint, SIGN_IN_REQUIRED_ATTR, False):
            raise HTTPException(status_code=303, headers={"Location": "/sign-in"})
        actor_role: str | None = GUEST
    else:
        if not user.email_verified:
            raise HTTPException(status_code=403, detail="Verify your email address first.")
        if sessions.needs_two_factor(request, user):
            raise HTTPException(status_code=303, headers={"Location": "/auth/2fa"})
        actor_role = user.role

    # AC1.3: asking for another tenant's data is refused outright, not quietly ignored.
    claimed = request.query_params.get("tenant_id")
    if claimed and (user is None or claimed != user.tenant_id):
        raise HTTPException(
            status_code=403,
            detail="You may only request data from your own workspace.",
        )

    if not role_has(actor_role, declared):
        raise HTTPException(
            status_code=403,
            detail=f"Your role ({actor_role or 'unknown'}) may not use {declared}.",
        )
