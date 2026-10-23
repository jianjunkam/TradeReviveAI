"""The whole US market, in memory.

Why this exists: the page shows the largest US companies, and a price for each, but
snapshot of all of them in one request. It will do 200 at a time in about 0.3s, so a full
sweep is ~36 requests and ~11 seconds. Doing that per page view would be absurd, and
sorting by change across the market is impossible from a single page.

So: one background thread sweeps the market every `refresh_seconds`, and every request is
answered from memory. The data therefore has an age, and the UI is told that age rather
than pretending it is tick-by-tick.

Nothing here invents a number: a row keeps whatever Yahoo reported, `None` stays `None`,
and a failed sweep keeps the previous rows while carrying the reason.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.broker.base import Broker, BrokerUnavailable, MarketRow

#: Columns a caller may sort by. Anything else is ignored, not interpolated.
SORTABLE = {
    "symbol",
    "name",
    "last_price",
    "change_rate",
    "volume",
    "turnover",
    "market_cap",
    "pe_ratio",
}
DESCENDING = {"change_rate", "volume", "turnover", "market_cap", "last_price"}


@dataclass
class MarketSnapshot:
    rows: list[MarketRow] = field(default_factory=list)
    loaded_at: datetime | None = None
    error: str | None = None
    universe_size: int = 0

    def age_seconds(self) -> float | None:
        if self.loaded_at is None:
            return None
        return round((datetime.now(timezone.utc) - self.loaded_at).total_seconds(), 1)

    @property
    def ready(self) -> bool:
        return bool(self.rows)


class MarketCache:
    """Holds the latest sweep; refreshes itself on a timer.

    Two speeds. The first refresh sweeps every listed stock (about 18 batched calls, ~20s)
    so the ranking is real; after that only the retained symbols are refreshed — one call
    for 100 stocks instead of eighteen for 6,400. The list is rebuilt every
    `rebuild_seconds` so it cannot drift out of date, without paying for a full sweep on
    every tick.
    """

    def __init__(
        self,
        broker: Broker,
        *,
        refresh_seconds: int = 30,
        top_n: int = 100,
        rebuild_seconds: int = 900,
    ) -> None:
        self._broker = broker
        self._refresh_seconds = max(15, int(refresh_seconds))
        self._top_n = max(1, int(top_n))
        self._rebuild_seconds = max(self._refresh_seconds, int(rebuild_seconds))
        self._lock = threading.Lock()
        self._snapshot = MarketSnapshot()
        self._symbols: list[str] | None = None
        self._symbols_at = 0.0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------ life

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="market-cache", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # A source that is down at boot must not crash a thread: retry on the next tick.
        while not self._stop.is_set():
            try:
                self.refresh()
            except Exception as exc:  # noqa: BLE001 - the loop must survive anything
                with self._lock:
                    self._snapshot.error = str(exc)
            self._stop.wait(self._refresh_seconds)

    # -------------------------------------------------------------- sweeping

    def refresh(self) -> MarketSnapshot:
        """One refresh: a full sweep when the ranking is due, otherwise just the top list."""
        try:
            rebuild = (
                self._symbols is None
                or (time.monotonic() - self._symbols_at) > self._rebuild_seconds
            )
            if rebuild:
                universe = self._broker.universe()
                codes = [info.symbol for info in universe]
                if not codes:
                    raise BrokerUnavailable("The broker returned no US stocks to sweep.")
                swept = self._broker.snapshots(codes)
                ranked = sorted(
                    (row for row in swept if row.market_cap),
                    key=lambda row: row.market_cap or 0,
                    reverse=True,
                )[: self._top_n]
                symbols = [row.symbol for row in ranked]
                if not symbols:
                    raise BrokerUnavailable(
                        "The broker returned no priced stocks with a market value."
                    )
                with self._lock:
                    self._symbols = symbols
                    self._symbols_at = time.monotonic()
                keep = set(symbols)
                rows = [row for row in ranked if row.symbol in keep]
            else:
                rows = self._broker.snapshots(list(self._symbols or []))
                rows = sorted(rows, key=lambda row: row.market_cap or 0, reverse=True)
        except BrokerUnavailable as exc:
            with self._lock:
                self._snapshot.error = str(exc)
            return self._snapshot

        with self._lock:
            self._snapshot = MarketSnapshot(
                rows=rows,
                loaded_at=datetime.now(timezone.utc),
                error=None,
                universe_size=len(rows),
            )
            return self._snapshot

    # --------------------------------------------------------------- reading

    def snapshot(self) -> MarketSnapshot:
        with self._lock:
            return self._snapshot

    def breadth(self) -> dict:
        snap = self.snapshot()
        gainers = losers = flat = unpriced = 0
        for row in snap.rows:
            if row.change_rate is None:
                unpriced += 1
            elif row.change_rate > 0:
                gainers += 1
            elif row.change_rate < 0:
                losers += 1
            else:
                flat += 1
        return {
            "gainers": gainers,
            "losers": losers,
            "flat": flat,
            "unpriced": unpriced,
            "total": len(snap.rows),
        }

    def query(
        self,
        *,
        q: str = "",
        sort: str = "change_rate",
        descending: bool | None = None,
        page: int = 1,
        size: int = 100,
    ) -> dict:
        """A page of the market: filtered, sorted across ALL rows, then sliced."""
        snap = self.snapshot()
        rows = snap.rows

        needle = q.strip().lower()
        if needle:
            rows = [
                r
                for r in rows
                if needle in r.symbol.lower() or needle in r.name.lower()
            ]

        key = sort if sort in SORTABLE else "change_rate"
        text_sort = key in {"symbol", "name"}
        if text_sort:
            descending = False
        elif descending is None:
            descending = key in DESCENDING

        # None sorts last either way: an unpriced stock is not the biggest loser.
        def sort_key(row: MarketRow):
            value = getattr(row, key, None)
            if value is None:
                return (1, 0, "")
            if text_sort:
                return (0, 0, str(value).lower())
            return (0, -value if descending else value, "")

        rows = sorted(rows, key=sort_key)

        total = len(rows)
        size = max(1, min(int(size), 500))
        pages = max(1, (total + size - 1) // size)
        page = max(1, min(int(page), pages))
        start = (page - 1) * size
        window = rows[start : start + size]

        return {
            "rows": [row.as_dict() for row in window],
            "total": total,
            "page": page,
            "pages": pages,
            "size": size,
            "sort": key,
            "descending": descending,
            "breadth": self.breadth(),
            "source": getattr(self._broker, "SOURCE", "market data"),
            "universe_size": snap.universe_size,
            "loaded_at": snap.loaded_at.isoformat() if snap.loaded_at else None,
            "age_seconds": snap.age_seconds(),
            "error": snap.error,
            "ready": snap.ready,
        }
