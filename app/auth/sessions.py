"""Session helpers: who is signed in, and have they passed two-factor.

The session is a signed cookie (Starlette's SessionMiddleware), never a token the client
can edit, and it is marked HttpOnly + Secure + SameSite=Lax in `create_app`.
"""

from __future__ import annotations

from fastapi import Request

from app.auth.store import MFA_REQUIRED_ROLES, AuthStore, User

SESSION_USER = "user_id"
SESSION_MFA = "mfa_verified"
SESSION_OAUTH_STATE = "oauth_state"


def _store(request: Request) -> AuthStore:
    return request.app.state.store


def start(request: Request, user: User, *, mfa_verified: bool = False) -> None:
    """Open a fresh session for this user. Any previous session is discarded."""
    session = request.session
    session.clear()
    session[SESSION_USER] = user.id
    session[SESSION_MFA] = mfa_verified


def clear(request: Request) -> None:
    request.session.clear()


def current_user(request: Request) -> User | None:
    """The signed-in user, re-read from the store on every request."""
    user_id = request.session.get(SESSION_USER)
    if not user_id:
        return None
    return _store(request).get_user(user_id)


def needs_two_factor(request: Request, user: User) -> bool:
    """Owners and admins are not signed in until they pass their second factor."""
    if user.role not in MFA_REQUIRED_ROLES:
        return False
    return not bool(request.session.get(SESSION_MFA))


def mark_two_factor_passed(request: Request) -> None:
    request.session[SESSION_MFA] = True
