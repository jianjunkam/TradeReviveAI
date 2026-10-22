"""Broker integration — read-only market data and positions from moomoo OpenD.

Nothing in here can place an order. The product's rules forbid trade execution and
buy/sell signals (AGENTS.md), so this layer only *reads*: quotes, positions, account
summary.

Two hard rules:

* Never invent a number. If OpenD is not reachable, the answer is "not connected" with a
  reason — not a sample price. A trader acting on a fabricated quote is worse off than one
  who sees an error.
* The SDK is imported lazily, so the app still starts and serves /demo on a machine where
  the native SDK is missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


class BrokerUnavailable(RuntimeError):
    """OpenD is not running, not logged in, or refused the request.

    The message is shown to the user, so it must say what to do next.
    """


@dataclass(frozen=True)
class BrokerStatus:
    connected: bool
    reason: str | None
    host: str
    port: int
    checked_at: datetime
    account: str | None = None

    def as_dict(self) -> dict:
        return {
            "connected": self.connected,
            "reason": self.reason,
            "host": self.host,
            "port": self.port,
            "account": self.account,
            "checked_at": self.checked_at.isoformat(),
        }


@dataclass(frozen=True)
class Quote:
    """One instrument, exactly as the broker reported it."""

    symbol: str
    name: str
    last_price: float
    previous_close: float
    change_rate: float  # percent, as the broker sends it
    volume: int
    bid: float | None
    ask: float | None
    updated_at: str | None
    # None means "the broker did not say", which is not the same as "real time".
    delayed: bool | None = None
    source: str = "moomoo OpenD"

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "last_price": self.last_price,
            "previous_close": self.previous_close,
            "change_rate": self.change_rate,
            "volume": self.volume,
            "bid": self.bid,
            "ask": self.ask,
            "updated_at": self.updated_at,
            "delayed": self.delayed,
            "source": self.source,
        }


@dataclass(frozen=True)
class Position:
    symbol: str
    name: str
    quantity: float
    cost_price: float
    market_price: float
    market_value: float
    unrealised_pl: float

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "quantity": self.quantity,
            "cost_price": self.cost_price,
            "market_price": self.market_price,
            "market_value": self.market_value,
            "unrealised_pl": self.unrealised_pl,
        }


@dataclass(frozen=True)
class SymbolInfo:
    """One listed instrument, without a price. The market's population."""

    symbol: str
    name: str
    exchange: str

    def as_dict(self) -> dict:
        return {"symbol": self.symbol, "name": self.name, "exchange": self.exchange}


@dataclass(frozen=True)
class MarketRow:
    """One instrument's latest state, as the broker reported it.

    `change_rate` is derived from last and previous close when the broker omits it, and is
    absent (None) when either price is missing — never defaulted to zero, because a flat
    0.00% on a stock that moved 8% is a lie the reader cannot detect.
    """

    symbol: str
    name: str
    last_price: float | None
    previous_close: float | None
    change_rate: float | None
    volume: int | None
    turnover: float | None
    market_cap: float | None
    pe_ratio: float | None
    bid: float | None
    ask: float | None
    updated_at: str | None

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "last_price": self.last_price,
            "previous_close": self.previous_close,
            "change_rate": self.change_rate,
            "volume": self.volume,
            "turnover": self.turnover,
            "market_cap": self.market_cap,
            "pe_ratio": self.pe_ratio,
            "bid": self.bid,
            "ask": self.ask,
            "updated_at": self.updated_at,
        }


class Broker(Protocol):
    """What the app is allowed to ask a broker. Read-only by construction."""

    def status(self) -> BrokerStatus: ...

    def quote(self, symbol: str) -> Quote: ...

    def positions(self) -> list[Position]: ...

    def universe(self) -> list[SymbolInfo]: ...

    def snapshots(self, symbols: list[str]) -> list[MarketRow]: ...


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
