"""Sign-in, sign-out, and the second factor.

Every route here decides for itself what it needs; the deny-by-default permission matrix
is M2's job and will sit in front of these (docs/AUTH.md). What M1 guarantees is that
nothing private is served without a session, and nothing at all is served to an account
that has not verified its email or passed its second factor.
"""

from __future__ import annotations

import html
import logging
import re
import secrets

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from app.auth import sessions, twofa
from app.auth.google import GoogleSignInError, GoogleProvider
from app.auth.store import AuthStore, User
from app.auth.throttle import Throttle
from app.auth.tokens import MAGIC_LINK_MAX_AGE, MagicLinkTokens
from app.permissions import public

router = APIRouter(include_in_schema=False)
logger = logging.getLogger("app.auth")

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterIn(BaseModel):
    email: str
    name: str = ""


# ------------------------------------------------------------------------ plumbing


def _store(request: Request) -> AuthStore:
    return request.app.state.store


def _tokens(request: Request) -> MagicLinkTokens:
    secret = request.app.state.settings.app_secret.get_secret_value()
    return MagicLinkTokens(secret, _store(request))


def _google(request: Request) -> GoogleProvider:
    return request.app.state.google


def _throttle(request: Request) -> Throttle:
    return Throttle(_store(request), request.app.state.clock)


def _ensure_totp(user: User, store: AuthStore) -> str:
    """Enrolment secret, created the first time the account is used."""
    if not user.totp_secret:
        user.totp_secret = twofa.new_secret()
        store.save_user(user)
    return user.totp_secret


def _safe_log(event: str, user: User) -> None:
    """One line per sign-in event: ids and outcome, never the address or a token."""
    logger.info("%s user=%s tenant=%s", event, user.id, user.tenant_id)


# -------------------------------------------------------------------------- pages


_SIGN_IN_PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Sign in · TradeRevive AI</title></head>
<body>
  <h1>Sign in</h1>
  <p>We email you a link. No password to remember.</p>
  <form method="post" action="/auth/magic-link">
    <label for="email">Email</label>
    <input id="email" name="email" type="email" required autocomplete="email">
    <button type="submit">Email me a link</button>
  </form>
  <p><a href="/auth/google">Continue with Google</a></p>
</body>
</html>
"""


@router.get("/sign-in", response_class=HTMLResponse)
@public
def sign_in_page(request: Request) -> Response:
    user = sessions.current_user(request)
    if user is not None and not sessions.needs_two_factor(request, user):
        return RedirectResponse("/app", status_code=303)
    return HTMLResponse(_SIGN_IN_PAGE)


@router.post("/auth/register", status_code=201)
@public
def register(request: Request, payload: "RegisterIn") -> dict:
    """Create the account and its tenant workspace (AC1.1), then send a confirmation link.

    AC1.2 asks for a clear "already in use" answer, so this endpoint does disclose whether
    an address is registered. The sign-in endpoint keeps answering 202 for everyone.
    """
    address = payload.email.strip().lower()
    if not _EMAIL.match(address):
        raise HTTPException(status_code=400, detail="That is not a valid email address.")

    store = _store(request)
    if store.get_user_by_email(address) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"{address} is already in use. Sign in instead of registering again.",
        )

    user = store.upsert_user(
        email=address,
        name=payload.name.strip() or address.split("@")[0],
        provider="magic_link",
        email_verified=False,
    )
    token = _tokens(request).issue(user.id)
    link = str(request.url_for("redeem_magic_link", token=token))
    request.app.state.email_sender.send(
        to=address,
        subject="Confirm your TradeRevive AI account",
        text=f"Confirm your account and sign in: {link}\nThe link works once, for 15 minutes.",
    )
    _safe_log("registered", user)
    return {"user_id": user.id, "tenant_id": user.tenant_id}


# --------------------------------------------------------------------- magic link


@router.post("/auth/magic-link")
@public
def request_magic_link(request: Request, email: str = Form(...)) -> Response:
    """Always answers 202, so the endpoint cannot be used to discover who has an account."""
    address = email.strip().lower()
    if not _EMAIL.match(address):
        raise HTTPException(status_code=400, detail="That is not a valid email address.")

    store = _store(request)
    user = store.upsert_user(
        email=address,
        name=address.split("@")[0],
        provider="magic_link",
        email_verified=False,
    )
    _ensure_totp(user, store)

    token = _tokens(request).issue(user.id)
    link = str(request.url_for("redeem_magic_link", token=token))
    minutes = MAGIC_LINK_MAX_AGE // 60
    request.app.state.email_sender.send(
        to=address,
        subject="Your TradeRevive AI sign-in link",
        text=f"Sign in to TradeRevive AI: {link}\nThe link works once, for {minutes} minutes.",
    )
    _safe_log("sign_in_link_issued", user)
    return JSONResponse({"status": "sent"}, status_code=202)


@router.get("/auth/magic/{token}")
@public
def redeem_magic_link(request: Request, token: str) -> Response:
    user_id = _tokens(request).redeem(token)
    if user_id is None:
        raise HTTPException(
            status_code=400,
            detail="That sign-in link is invalid, expired, or already used.",
        )

    store = _store(request)
    user = store.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="That account no longer exists.")

    # Following a link we mailed to the address is what verifies the address.
    if not user.email_verified:
        user.email_verified = True
        store.save_user(user)
    _ensure_totp(user, store)

    sessions.start(request, user)
    _safe_log("sign_in_magic_link", user)
    return RedirectResponse("/app", status_code=303)


# ------------------------------------------------------------------------- google


@router.get("/auth/google")
@public
def google_start(request: Request) -> Response:
    state = secrets.token_urlsafe(24)
    request.session[sessions.SESSION_OAUTH_STATE] = state
    redirect_uri = str(request.url_for("google_callback"))
    try:
        url = _google(request).authorize_url(state=state, redirect_uri=redirect_uri)
    except GoogleSignInError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return RedirectResponse(url, status_code=303)


@router.get("/auth/google/callback")
@public
def google_callback(
    request: Request, code: str = Query(...), state: str = Query(...)
) -> Response:
    expected = request.session.pop(sessions.SESSION_OAUTH_STATE, None)
    if not expected or not secrets.compare_digest(str(expected), state):
        raise HTTPException(
            status_code=400, detail="This sign-in attempt could not be verified. Start again."
        )

    redirect_uri = str(request.url_for("google_callback"))
    try:
        identity = _google(request).exchange(code=code, redirect_uri=redirect_uri)
    except GoogleSignInError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not identity.email_verified:
        # An address Google will not vouch for is not a key to this app.
        logger.info("sign_in_refused_unverified_provider=google")
        raise HTTPException(
            status_code=403, detail="Verify your email address with Google before signing in."
        )

    store = _store(request)
    user = store.upsert_user(
        email=identity.email,
        name=identity.name or identity.email.split("@")[0],
        provider="google",
        email_verified=True,
    )
    _ensure_totp(user, store)

    sessions.start(request, user)
    _safe_log("sign_in_google", user)
    return RedirectResponse("/app", status_code=303)


# ------------------------------------------------------------------- two factor


@router.get("/auth/2fa", response_class=HTMLResponse)
@public
def two_factor_page(request: Request) -> Response:
    user = sessions.current_user(request)
    if user is None:
        return RedirectResponse("/sign-in", status_code=303)
    if not sessions.needs_two_factor(request, user):
        return RedirectResponse("/app", status_code=303)

    secret = _ensure_totp(user, _store(request))
    uri = html.escape(twofa.provisioning_uri(secret, email=user.email), quote=True)
    page = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Two-factor · TradeRevive AI</title></head>
<body>
  <h1>One more step</h1>
  <p>Add this account to your authenticator app, then enter the six-digit code.</p>
  <p><code>{uri}</code></p>
  <form method="post" action="/auth/2fa">
    <label for="code">Code</label>
    <input id="code" name="code" inputmode="numeric" autocomplete="one-time-code" required>
    <button type="submit">Verify</button>
  </form>
</body>
</html>
"""
    return HTMLResponse(page)


@router.post("/auth/2fa")
@public
def two_factor_submit(request: Request, code: str = Form(...)) -> Response:
    user = sessions.current_user(request)
    if user is None:
        return RedirectResponse("/sign-in", status_code=303)

    throttle = _throttle(request)
    key = f"mfa:{user.id}"

    waiting = throttle.check(key)
    if waiting is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Wait before trying again.",
            headers={"Retry-After": str(waiting)},
        )

    if not user.totp_secret or not twofa.verify(user.totp_secret, code):
        waiting = throttle.record_failure(key)
        if waiting is not None:
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Wait before trying again.",
                headers={"Retry-After": str(waiting)},
            )
        raise HTTPException(status_code=401, detail="That code is not valid.")

    throttle.clear(key)
    sessions.mark_two_factor_passed(request)
    _safe_log("sign_in_two_factor_passed", user)
    return RedirectResponse("/app", status_code=303)


# ------------------------------------------------------------------------ sign out


@router.post("/auth/sign-out")
@public
def sign_out(request: Request) -> Response:
    user = sessions.current_user(request)
    if user is not None:
        _safe_log("sign_out", user)
    sessions.clear(request)
    return RedirectResponse("/sign-in", status_code=303)
