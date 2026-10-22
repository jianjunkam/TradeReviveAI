"""Guarded endpoints: one per permission the M2 tests need.

These are plumbing, not features. M3 builds the real trade, analytics and report routes;
what lives here is the matrix being applied to HTTP, including one route
(`/internal/debug`) that declares nothing on purpose, so deny-by-default has a live
canary the tests can poke.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.auth import sessions
from app.auth.store import ADMIN, GUEST, TRADER
from app.i18n import LANGUAGES
from app.permissions import (
    F_AUTH,
    P_AI,
    P_EXPORT,
    P_SETTINGS,
    P_TEAM,
    P_USAGE,
    permit,
)

router = APIRouter(include_in_schema=False)


def _signed_in(request: Request):
    """The guard has already refused anonymous callers on these routes."""
    user = sessions.current_user(request)
    if user is None:  # pragma: no cover - belt and braces behind the guard
        raise HTTPException(status_code=401, detail="Sign in first.")
    return user


@router.get("/account")
@permit(F_AUTH)
def account(request: Request) -> dict[str, str]:
    user = _signed_in(request)
    return {
        "id": user.id,
        "tenant_id": user.tenant_id,
        "role": user.role,
        "email": user.email,
        "language": user.language_preference,
    }


class LanguageChange(BaseModel):
    language: str


@router.patch("/account/language")
@permit(F_AUTH)
def change_language(request: Request, body: LanguageChange) -> dict[str, str]:
    """AC1.4: swap the string dictionary. No model call, no cost, same answer every time."""
    user = _signed_in(request)
    if body.language not in LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"language must be one of {', '.join(LANGUAGES)}",
        )
    user.language_preference = body.language
    request.app.state.store.save_user(user)
    return {"language": user.language_preference}


@router.get("/team/roles")
@permit(P_TEAM)
def team_roles(request: Request) -> dict[str, object]:
    user = _signed_in(request)
    return {"tenant_id": user.tenant_id, "roles": [TRADER, GUEST, ADMIN]}


class RoleChange(BaseModel):
    user_id: str
    role: str


@router.post("/team/roles")
@permit(P_TEAM)
def change_role(request: Request, body: RoleChange) -> dict[str, str]:
    actor = _signed_in(request)
    if body.role not in (TRADER, GUEST, ADMIN):
        raise HTTPException(status_code=400, detail=f"{body.role!r} is not a role.")

    target = request.app.state.store.get_user(body.user_id)
    # Another customer's user does not exist as far as this tenant is concerned.
    if target is None or target.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=404, detail="No such user in this workspace.")

    target.role = body.role
    request.app.state.store.save_user(target)
    return {"user_id": target.id, "role": target.role}


@router.get("/admin/ai-settings")
@permit(P_AI)
def ai_settings() -> dict[str, object]:
    # Read-only placeholder; M4 owns the real settings and the budget.
    return {"model": "deepseek-flash", "budget_rm_month": 5}


@router.get("/admin/usage")
@permit(P_USAGE)
def usage(request: Request) -> dict[str, object]:
    user = _signed_in(request)
    return {"tenant_id": user.tenant_id, "records": request.app.state.tenancy.scope(user.tenant_id).counts()}


@router.get("/export")
@permit(P_EXPORT)
def export(request: Request) -> dict[str, object]:
    """Exports the caller's own tenant. A `tenant_id` in the query string is ignored."""
    user = _signed_in(request)
    scope = request.app.state.tenancy.scope(user.tenant_id)
    return {"tenant_id": user.tenant_id, "records": scope.counts()}


@router.get("/settings")
@permit(P_SETTINGS)
def settings(request: Request) -> dict[str, object]:
    user = sessions.current_user(request)
    # The matrix grants Guest "Business settings", so this answers anonymous callers too.
    return {"language": user.language_preference if user else "en"}


@router.get("/internal/debug")
def undeclared_route() -> dict[str, str]:
    """No @permit and no @public: the guard must refuse this for everyone."""
    return {"detail": "this should never be reachable"}
