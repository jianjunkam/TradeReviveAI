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
from app.auth.demo import DEMO_EMAIL, ensure_demo_session
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


_SIGN_IN_PAGE = _SIGN_IN_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sign in · TradeRevive AI</title>
  <link rel="stylesheet" href="/static/app.css">
</head>
<body>
<div class="auth">
  <div class="auth-card">
    <div class="brand">
      <span class="mark">TR</span>
      <span>TradeRevive AI<small>Trading recovery platform</small></span>
    </div>

    <ol class="steps" aria-label="Sign-in progress">
      <li class="step active" id="step-email">1 · Email</li>
      <li class="step" id="step-code">2 · Passcode</li>
    </ol>

    <div class="alert" id="alert" role="alert" hidden></div>

    <!-- Step 1: the address -->
    <form id="email-form" novalidate>
      <h1>Sign in</h1>
      <p class="lede">We email you a one-time link. No password to remember, nothing to leak.</p>
      <div class="field">
        <label for="email">Email address</label>
        <input id="email" name="email" type="email" required autocomplete="email"
               placeholder="you@example.com" autofocus>
      </div>
      <button class="btn" type="submit" id="email-submit">Continue</button>
      <div class="divider">or</div>
      <a class="btn secondary" href="/auth/google">Continue with Google</a>
      <a class="muted-link" href="/demo">See the demo dashboard &rarr;</a>
    </form>

    <!-- Outside the email form: nested <form> elements are dropped by the HTML parser. -->
    <form method="post" action="/auth/demo" id="demo-form" hidden>
      <button class="btn secondary" type="submit">Enter the demo account</button>
      <p class="muted-note">No email, no passcode — for reviewing this build.</p>
    </form>

    <!-- Step 2: the passcode, shown as soon as the address is submitted -->
    <section id="code-panel" hidden>
      <h1>Enter your passcode</h1>
      <p class="lede" id="code-lede">Six digits from your authenticator app.</p>

      <div class="sent" id="sent-note" hidden>
        <strong>Check your inbox.</strong> Open the sign-in link we sent to
        <span id="sent-address" class="mono"></span>, then enter the code below.
      </div>

      <form id="code-form" novalidate>
        <div class="field">
          <label for="code">Six-digit code</label>
          <input id="code" name="code" class="code-input" inputmode="numeric"
                 autocomplete="one-time-code" maxlength="6" pattern="[0-9]{6}"
                 required autofocus>
        </div>
        <button class="btn" type="submit" id="code-submit">Verify and sign in</button>
      </form>

      <button class="linkish" type="button" id="back">&larr; Use a different email</button>
    </section>

    <p class="dev-banner" id="dev-banner" hidden>
      <strong>Development mode.</strong> No email leaves this machine — the sign-in link is
      printed in the terminal running the app, and this page skips it so you can go straight
      to the passcode. Production sends the email and requires the link.
      <span id="setup-line" hidden><br>
        <strong>Setup key:</strong> <code id="setup-key" class="mono"></code> — add it to your
        authenticator app (or compute the code with pyotp) to get the six digits.
      </span>
    </p>
  </div>
</div>
<script>__CONFIG__</script>
<script src="/static/signin.js"></script>
</body>
</html>
"""


def _sign_in_page(
    *,
    started: bool,
    dev: bool,
    setup_key: str | None = None,
    demo: bool = False,
) -> str:
    """Render the page with the state the server already knows.

    `started` means a session exists and only the passcode is outstanding (the user has
    just followed the emailed link in another tab). `dev` is the development-mode banner;
    `setup_key` is the TOTP secret, and it is only ever passed in development, where the
    emailed link — and therefore the enrolment page — is skipped.
    """
    config = "window.__signin = { started: %s, dev: %s, setupKey: %r, demo: %s };" % (
        "true" if started else "false",
        "true" if dev else "false",
        setup_key or "",
        "true" if demo else "false",
    )
    return _SIGN_IN_TEMPLATE.replace("__CONFIG__", config)


@router.get("/sign-in", response_class=HTMLResponse)
@public
def sign_in_page(request: Request) -> Response:
    settings = request.app.state.settings
    if not settings.require_sign_in:
        # There is no login page when sign-in is off: go straight into the workspace.
        return RedirectResponse("/app", status_code=303)
    dev = settings.environment == "development"
    demo = settings.demo_sign_in
    user = sessions.current_user(request)
    if user is not None:
        if not sessions.needs_two_factor(request, user):
            return RedirectResponse("/app", status_code=303)
        # A session exists and only the passcode is outstanding: show step 2 straight away.
        # In development the enrolment page was skipped with the link, so the setup key is
        # shown in the banner — otherwise there would be no way to produce a valid code.
        return HTMLResponse(
            _sign_in_page(
                started=True,
                dev=dev,
                setup_key=user.totp_secret if dev else None,
                demo=demo,
            )
        )
    return HTMLResponse(_sign_in_page(started=False, dev=dev, demo=demo))


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


# ------------------------------------------------------------------- demo sign-in


DEMO_EMAIL = "demo@traderevive.local"


@router.post("/auth/demo")
@public
def demo_sign_in(request: Request) -> Response:
    """Sign in as the demo account: no email link, no passcode.

    No mail provider is wired, so a hosted copy of this demo cannot send a magic link and
    therefore cannot be signed into at all. This route is that way in, on purpose — it is
    switched by DEMO_SIGN_IN and it only ever signs in one fixed local account.
    """
    settings = request.app.state.settings
    if not settings.demo_sign_in:
        raise HTTPException(status_code=404, detail="Not found.")

    # Both factors are deliberately satisfied: that is the whole point of the button.
    user = ensure_demo_session(request)
    _safe_log("demo_sign_in", user)
    return RedirectResponse("/app", status_code=303)


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

    # Development has no email transport, so the page would be stuck at step 1. Open a
    # half-session here (the passcode is still required) and let the page skip to step 2.
    # Outside development this never runs: the emailed link is the credential.
    dev_mode = request.app.state.settings.environment == "development"
    if dev_mode:
        if not user.email_verified:
            user.email_verified = True
            store.save_user(user)
        sessions.start(request, user)

    return JSONResponse(
        {
            "status": "sent",
            "dev_mode": dev_mode,
            "next": "/auth/2fa" if dev_mode else None,
        },
        status_code=202,
    )


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
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Two-factor · TradeRevive AI</title>
  <link rel="stylesheet" href="/static/app.css">
</head>
<body>
<div class="auth">
  <div class="auth-card">
    <div class="brand">
      <span class="mark">TR</span>
      <span>TradeRevive AI<small>Trading recovery platform</small></span>
    </div>
    <h1>One more step</h1>
    <p class="lede">Add this account to your authenticator app, then enter the six-digit code.</p>
    <p class="sub">Manual setup key</p>
    <code class="code">{uri}</code>
    <form method="post" action="/auth/2fa" style="margin-top:16px">
      <div class="field">
        <label for="code">Six-digit code</label>
        <input id="code" name="code" inputmode="numeric" autocomplete="one-time-code"
               required placeholder="123456">
      </div>
      <button class="btn" type="submit">Verify</button>
    </form>
  </div>
</div>
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
