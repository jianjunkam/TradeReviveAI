"""The public dashboard's data: live quotes and positions with no sign-in.

This exists because the human asked for the product's front page to work without a login,
showing their own moomoo data. That is a real trade-off and it is fenced deliberately:

  * off unless `PUBLIC_DASHBOARD=true` (default false),
  * the app must be reachable on 127.0.0.1 only, because positions are private,
  * it is read-only: no order endpoints, no account identifiers beyond the broker's own.

When the flag is off the route answers 404 — not 403 — so a production deployment that
forgot to set it looks like the feature does not exist.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.broker.base import Broker, BrokerUnavailable
from app.permissions import public

router = APIRouter(prefix="/api/public", include_in_schema=False)


def _broker(request: Request) -> Broker:
    return request.app.state.broker


@router.get("/market")
@public
def public_market(request: Request) -> dict:
    settings = request.app.state.settings
    if settings.demo_closed:
        raise HTTPException(status_code=404, detail="Not found.")

    broker = _broker(request)
    status = broker.status()

    symbols = [s.strip().upper() for s in settings.demo_watchlist.split(",") if s.strip()]
    quotes: list[dict] = []
    for symbol in symbols:
        try:
            quotes.append(broker.quote(symbol).as_dict())
        except BrokerUnavailable as exc:
            # One symbol without permission must not blank the whole strip.
            quotes.append({"symbol": symbol, "error": str(exc)})

    positions: list[dict] = []
    positions_error: str | None = None
    # Positions are the one private thing here: a public demo shows the market, not the
    # account. They are returned only when PUBLIC_POSITIONS is set explicitly.
    if settings.public_positions:
        try:
            positions = [position.as_dict() for position in broker.positions()]
        except BrokerUnavailable as exc:
            positions_error = str(exc)
    else:
        positions_error = "Positions are private on this deployment."

    return {
        "broker": status.as_dict(),
        "quotes": quotes,
        "positions": positions,
        "positions_error": positions_error,
        "positions_hidden": not settings.public_positions,
        "watchlist": symbols,
    }


@router.get("/us/market")
@public
def us_market(
    request: Request,
    q: str = "",
    sort: str = "change_rate",
    dir: str = "auto",
    page: int = 1,
    size: int = 100,
) -> dict:
    """A page of the whole US market, sorted across every listed stock.

    Served from the cache, so `age_seconds` tells the caller how old the numbers are.
    """
    settings = request.app.state.settings
    if settings.demo_closed:
        raise HTTPException(status_code=404, detail="Not found.")

    descending = None
    if dir.lower() in {"asc", "desc"}:
        descending = dir.lower() == "desc"

    cache = request.app.state.market
    return cache.query(q=q, sort=sort, descending=descending, page=page, size=size)


@router.get("/news")
@public
def market_news(request: Request, limit: int = 8) -> dict:
    """Today's market headlines, from Yahoo Finance's RSS feed.

    Cached for ten minutes: it is somebody else's server, and headlines do not change
    faster than that.
    """
    settings = request.app.state.settings
    if settings.demo_closed:
        raise HTTPException(status_code=404, detail="Not found.")
    return request.app.state.news.get(limit=limit)
