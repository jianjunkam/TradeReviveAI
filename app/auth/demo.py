"""The demo identity.

There is no mail provider, so a deployed copy cannot deliver a magic link and the login page
would be a wall. Rather than fake an email, the app has one fixed account and — unless
sign-in is turned back on — every visitor is that account.
"""

from __future__ import annotations

from fastapi import Request

from app.auth import sessions
from app.auth.store import User

DEMO_EMAIL = "demo@traderevive.local"


def ensure_demo_user(store) -> User:
    """Create the demo account the first time it is needed, then reuse it."""
    user = store.get_user_by_email(DEMO_EMAIL)
    if user is None:
        return store.upsert_user(
            email=DEMO_EMAIL,
            name="Demo trader",
            provider="demo",
            email_verified=True,
        )
    if not user.email_verified:
        user.email_verified = True
        store.save_user(user)
    return user


def ensure_demo_session(request: Request) -> User:
    """Sign the visitor in as the demo account if they are not already someone."""
    user = sessions.current_user(request)
    if user is not None:
        return user
    user = ensure_demo_user(request.app.state.store)
    sessions.start(request, user, mfa_verified=True)
    return user
