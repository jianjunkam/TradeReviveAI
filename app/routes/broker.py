"""Broker endpoints: status, one quote, and open positions.

Read-only. There is no endpoint that places, changes or cancels an order, and none will be
added: AGENTS.md forbids execution and any buy/sell instruction from this product.

When the source is unreachable every endpoint says so with a 503 and a reason. None of them
falls back to sample data.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.broker.base import Broker, BrokerUnavailable
from app.permissions import F_IMPORT, permit

router = APIRouter(prefix="/api/broker", include_in_schema=False)


def _broker(request: Request) -> Broker:
    return request.app.state.broker


@router.get("/status")
@permit(F_IMPORT, sign_in_required=True)
def broker_status(request: Request) -> dict:
    """Always 200: "not connected" is a normal answer, not an error."""
    return _broker(request).status().as_dict()


@router.get("/quote")
@permit(F_IMPORT, sign_in_required=True)
def broker_quote(request: Request, symbol: str = Query(..., max_length=32)) -> dict:
    try:
        return _broker(request).quote(symbol).as_dict()
    except BrokerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/positions")
@permit(F_IMPORT, sign_in_required=True)
def broker_positions(request: Request) -> dict:
    try:
        return {"positions": [position.as_dict() for position in _broker(request).positions()]}
    except BrokerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
