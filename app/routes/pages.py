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

    # Checking the broker is a separate click: it makes a network call, and a page load
    # should not stall (or fail) because a local gateway is not running.
    if request.query_params.get("check") == "1":
        broker_state = request.app.state.broker.status()
        if broker_state.connected:
            broker_block = (
                "<p class='sub'>Prices from Yahoo Finance. "
                f"{html.escape(broker_state.host)}:{broker_state.port}. "
                "Quotes and positions come straight from your broker.</p>"
                "<span class='tag'>live</span>"
            )
        else:
            broker_block = (
                f"<p class='sub'>{html.escape(broker_state.reason or 'Not connected.')}</p>"
                "<span class='tag' style='background:#fee2e2;color:#991b1b'>not connected</span>"
            )
    else:
        broker_block = (
            "<p class='sub'>Not checked yet. Checking contacts your broker through the "
            "The feed is unofficial and may be delayed.</p>"
            "<a class='btn secondary' style='width:auto;display:inline-flex;padding:8px 14px' "
            "href='/app?check=1'>Check connection</a>"
        )

    page = f"""<!doctype html>
<html lang="{html.escape(language)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{t(language, "workspace")} · TradeRevive AI</title>
  <link rel="stylesheet" href="/static/app.css">
</head>
<body>
<div class="main" style="max-width:780px;margin:0 auto">
  <div class="topbar">
    <div>
      <h1>{t(language, "workspace")}</h1>
      <p>{t(language, "signed_in_as")} {html.escape(user.email)} ({html.escape(user.role)})</p>
    </div>
    <form method="post" action="/auth/sign-out">
      <button class="ghost" type="submit">{t(language, "sign_out")}</button>
    </form>
  </div>

  <div class="card">
    <h2>{t(language, "tenant")}</h2>
    <p class="sub">Your data lives in this workspace and nowhere else.</p>
    <span class="tenant-chip" data-tenant="{html.escape(user.tenant_id)}">{html.escape(user.tenant_id)}</span>
  </div>

  <div class="card" style="margin-top:16px">
    <h2>Broker connection</h2>
    {broker_block}
  </div>

  <div class="card" style="margin-top:16px">
    <h2>Design preview</h2>
    <p class="sub">The dashboard layout, filled with sample data.</p>
    <a class="muted-link" style="text-align:left;margin:0" href="/demo">Open the demo dashboard &rarr;</a>
  </div>
</div>
</body>
</html>
"""
    return HTMLResponse(page)
