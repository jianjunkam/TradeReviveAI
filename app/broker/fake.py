"""A fake broker for tests. Never wired into a running app.

`create_app` never chooses this class; only a test constructs it explicitly. That is
deliberate: sample prices on a dashboard are indistinguishable from live ones, which is
the one mistake this feature must not make.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.broker.base import (
    BrokerStatus,
    BrokerUnavailable,
    MarketRow,
    Position,
    Quote,
    SymbolInfo,
)


class FakeBroker:
    def __init__(
        self,
        *,
        connected: bool = True,
        reason: str | None = None,
        quotes: dict[str, Quote] | None = None,
        positions: list[Position] | None = None,
        universe: list[SymbolInfo] | None = None,
        rows: list[MarketRow] | None = None,
    ) -> None:
        self._connected = connected
        self._reason = reason
        self._quotes = quotes or {}
        self._positions = positions or []
        self._universe = universe or []
        self._rows = {row.symbol: row for row in (rows or [])}

    def status(self) -> BrokerStatus:
        return BrokerStatus(
            connected=self._connected,
            reason=self._reason,
            host="127.0.0.1",
            port=11111,
            checked_at=datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc),
            account="TEST-ACCOUNT" if self._connected else None,
        )

    def quote(self, symbol: str) -> Quote:
        if not self._connected:
            raise BrokerUnavailable(self._reason or "not connected")
        quote = self._quotes.get(symbol.upper())
        if quote is None:
            raise BrokerUnavailable(f"the fake broker has no quote for {symbol}")
        return quote

    def positions(self) -> list[Position]:
        if not self._connected:
            raise BrokerUnavailable(self._reason or "not connected")
        return list(self._positions)

    # ------------------------------------------------------- whole-market reads

    def universe(self) -> list[SymbolInfo]:
        if not self._connected:
            raise BrokerUnavailable(self._reason or "not connected")
        return list(getattr(self, "_universe", []))

    def snapshots(self, symbols: list[str]) -> list[MarketRow]:
        if not self._connected:
            raise BrokerUnavailable(self._reason or "not connected")
        rows = getattr(self, "_rows", {})
        return [rows[s] for s in symbols if s in rows]
