"""Paper-trading endpoints. Simulated fills at the broker's last price.

Everything is fenced behind the same `DEMO_CLOSED` switch as the rest of the demo,
and no endpoint can reach a real trading context — `PaperStore` writes to a JSON file.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.broker.base import BrokerUnavailable
from app.paper import PaperError, PaperStore
from app.permissions import public

router = APIRouter(prefix="/api/paper", include_in_schema=False)


class OrderRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=24)
    side: str = Field(pattern="^(buy|sell)$")
    quantity: int = Field(gt=0, le=100_000)


def _gate(request: Request) -> PaperStore:
    if request.app.state.settings.demo_closed:
        raise HTTPException(status_code=404, detail="Not found.")
    return request.app.state.paper


def _marks(request: Request) -> dict[str, float]:
    """Live marks for the holdings, from the market cache. Missing symbols are marked at cost."""
    cache = request.app.state.market
    store: PaperStore = request.app.state.paper
    if cache is None:
        return {}
    rows = {row.symbol: row.last_price for row in cache.snapshot().rows}
    return {
        symbol: rows[symbol]
        for symbol in store.account().holdings
        if rows.get(symbol)
    }


@router.get("/account")
@public
def account(request: Request) -> dict:
    store = _gate(request)
    return store.account().state(_marks(request))


@router.get("/quote")
@public
def quote(request: Request, symbol: str) -> dict:
    """The price an order would fill at, straight from the broker."""
    _gate(request)
    try:
        live = request.app.state.broker.quote(symbol)
    except BrokerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "symbol": live.symbol,
        "name": live.name,
        "last_price": live.last_price,
        "change_rate": live.change_rate,
        "updated_at": live.updated_at,
    }


@router.post("/order")
@public
def place_order(request: Request, payload: OrderRequest) -> dict:
    store = _gate(request)
    try:
        live = request.app.state.broker.quote(payload.symbol)
    except BrokerUnavailable as exc:
        # Never fill on a price we could not read.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        fill = store.order(
            payload.symbol, payload.side, payload.quantity, Decimal(str(live.last_price))
        )
    except PaperError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "fill": fill.as_dict(),
        "account": store.account().state(_marks(request)),
    }


@router.post("/reset")
@public
def reset(request: Request) -> dict:
    store = _gate(request)
    store.reset()
    return {"account": store.account().state(_marks(request))}
