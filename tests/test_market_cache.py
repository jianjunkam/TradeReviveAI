"""The whole-market cache: sorting, paging and search across every row.

The behaviour worth pinning is the one a page-scoped implementation would get wrong:
sorting by change rate must order the ENTIRE market, not the 100 rows on screen, and an
unpriced stock must never masquerade as the biggest mover in either direction.
"""

from __future__ import annotations

from app.broker.base import MarketRow, SymbolInfo
from app.broker.fake import FakeBroker
from app.market import MarketCache


def _row(symbol: str, name: str, price: float | None, change: float | None, volume: int, cap: float) -> MarketRow:
    return MarketRow(
        symbol=symbol,
        name=name,
        last_price=price,
        previous_close=(price - change) if price is not None and change is not None else None,
        change_rate=change,
        volume=volume,
        turnover=float(volume) * (price or 0),
        market_cap=cap,
        pe_ratio=20.0,
        bid=None,
        ask=None,
        updated_at="2026-10-22 15:00:00",
    )


def _cache() -> MarketCache:
    rows = [
        _row("US.AAPL", "Apple", 343.99, 1.32, 35_000_000, 5.02e12),
        _row("US.NVDA", "NVIDIA", 221.97, 2.54, 190_000_000, 5.35e12),
        _row("US.TSLA", "Tesla", 400.0, -4.10, 90_000_000, 1.2e12),
        _row("US.RBNE", "Robin Energy", 0.23, -41.80, 12_000, 3.0e7),
        _row("US.HALT", "Halted Corp", None, None, 0, 1.0e8),
    ]
    universe = [SymbolInfo(symbol=r.symbol, name=r.name, exchange="NASDAQ") for r in rows]
    broker = FakeBroker(universe=universe, rows=rows)
    cache = MarketCache(broker)
    cache.refresh()
    return cache


def test_a_sweep_fills_the_cache():
    snap = _cache().snapshot()

    assert snap.ready
    assert len(snap.rows) == 5
    assert snap.error is None
    assert snap.age_seconds() is not None and snap.age_seconds() >= 0


def test_sorted_by_change_descending_covers_the_whole_market():
    result = _cache().query(sort="change_rate", descending=True, page=1, size=2)

    # The biggest mover is on page 1 of the full market, not merely of a pre-sliced page.
    assert [r["symbol"] for r in result["rows"]] == ["US.NVDA", "US.AAPL"]
    assert result["total"] == 5
    assert result["pages"] == 3


def test_paging_walks_the_sorted_market():
    cache = _cache()

    page1 = cache.query(sort="change_rate", descending=True, page=1, size=2)
    page2 = cache.query(sort="change_rate", descending=True, page=2, size=2)
    page3 = cache.query(sort="change_rate", descending=True, page=3, size=2)

    assert [r["symbol"] for r in page2["rows"]] == ["US.TSLA", "US.RBNE"]
    assert [r["symbol"] for r in page3["rows"]] == ["US.HALT"]


def test_an_unpriced_stock_sorts_last_but_is_still_counted():
    result = _cache().query(sort="change_rate", descending=True, page=1, size=10)

    assert result["rows"][-1]["symbol"] == "US.HALT"
    assert result["breadth"]["unpriced"] == 1
    assert result["breadth"]["gainers"] == 2
    assert result["breadth"]["losers"] == 2


def test_search_matches_code_or_name_and_ignores_case():
    cache = _cache()

    assert [r["symbol"] for r in cache.query(q="nvd")["rows"]] == ["US.NVDA"]
    assert [r["symbol"] for r in cache.query(q="APPLE")["rows"]] == ["US.AAPL"]
    assert cache.query(q="zzzz")["total"] == 0


def test_sort_by_volume_orders_by_turnover_of_shares():
    result = _cache().query(sort="volume", descending=True, page=1, size=3)

    assert [r["symbol"] for r in result["rows"]] == ["US.NVDA", "US.TSLA", "US.AAPL"]


def test_an_unknown_sort_column_falls_back_instead_of_erroring():
    result = _cache().query(sort="'; drop table trades; --", page=1, size=5)

    assert result["sort"] == "change_rate"
    assert result["rows"]


def test_page_beyond_the_end_is_clamped():
    result = _cache().query(page=99, size=2)

    assert result["page"] == result["pages"]


def test_a_failed_sweep_keeps_the_reason_and_no_rows():
    broker = FakeBroker(connected=False, reason="Yahoo Finance did not answer")
    cache = MarketCache(broker)

    snap = cache.refresh()

    assert snap.rows == []
    assert "Yahoo Finance did not answer" in (snap.error or "")
    assert cache.query()["ready"] is False
