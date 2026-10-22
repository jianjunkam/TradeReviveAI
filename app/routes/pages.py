"""The signed-in pages. In M1 there is exactly one: the private page the tests attack."""

from __future__ import annotations

import html

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.auth import sessions
from app.i18n import t
from app.permissions import F_AUTH, permit

router = APIRouter(include_in_schema=False)


@router.get("/app", response_class=HTMLResponse)
@permit(F_AUTH, sign_in_required=True)
def private_page(request: Request) -> Response:
    # The guard has already checked the role and the second factor; these checks stay as
    # defence in depth for anyone who mounts this router without it.
    user = sessions.current_user(request)
    if user is None:
        return RedirectResponse("/sign-in", status_code=303)
    if not user.email_verified:
        raise HTTPException(status_code=403, detail="Verify your email address first.")
    if sessions.needs_two_factor(request, user):
        return RedirectResponse("/auth/2fa", status_code=303)

    language = user.language_preference
    page = f"""<!doctype html>
<html lang="{html.escape(language)}">
<head><meta charset="utf-8"><title>{t(language, "workspace")} · TradeRevive AI</title></head>
<body>
  <h1>{t(language, "workspace")}</h1>
  <p>{t(language, "signed_in_as")} {html.escape(user.email)} ({html.escape(user.role)}).</p>
  <p data-tenant="{html.escape(user.tenant_id)}">{t(language, "tenant")}: {html.escape(user.tenant_id)}</p>
  <form method="post" action="/auth/sign-out"><button type="submit">{t(language, "sign_out")}</button></form>
</body>
</html>
"""
    return HTMLResponse(page)
