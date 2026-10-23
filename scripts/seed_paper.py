"""Seed the paper account with trades at real historical closes.

Why historical: a trade opened at today's price has no P&L until tomorrow, so a freshly
seeded journal would be a flat line of zeros. Every fill below is priced from an actual
daily close from Yahoo Finance — the wins and the losses are what the market did, not what
we wanted the demo to look like.

Run it from the repo root:

    ./.venv/Scripts/python.exe scripts/seed_paper.py --per-symbol 6

It resets the account first, so it is repeatable. Historical K-line quota is 100 requests
per day; one request per symbol covers it.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.paper import PaperError, PaperStore  # noqa: E402

SYMBOLS = [
    "US.AAPL", "US.MSFT", "US.NVDA", "US.AMZN", "US.GOOGL",
    "US.META", "US.TSLA", "US.JPM", "US.XOM", "US.KO",
]
HOLD_DAYS = [3, 2, 5, 4, 2, 6]  # deterministic, varied on purpose


def candles(symbol: str, days: int) -> list[tuple[str, Decimal]]:
    """Daily closes from Yahoo's chart endpoint: one request per symbol, no account."""
    code = symbol[3:] if symbol.upper().startswith("US.") else symbol.upper()
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{code}?range=1y&interval=1d&includePrePost=false"
    )
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "*/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001 - a seed that cannot read a price must say so
        print(f"  {symbol}: no candles ({exc})")
        return []

    result = ((payload.get("chart") or {}).get("result") or [{}])[0]
    stamps = result.get("timestamp") or []
    closes = (((result.get("indicators") or {}).get("quote") or [{}])[0].get("close")) or []

    rows: list[tuple[str, Decimal]] = []
    for stamp, close in zip(stamps, closes):
        if close is None or float(close) <= 0:
            continue
        rows.append((
            datetime.fromtimestamp(int(stamp), tz=timezone.utc).strftime("%Y-%m-%d"),
            Decimal(str(round(float(close), 4))),
        ))
    time.sleep(0.4)  # be a polite guest
    return rows[-days:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--per-symbol", type=int, default=6)
    parser.add_argument("--store", default="data/paper.json")
    parser.add_argument("--cash", default="100000")
    args = parser.parse_args()

    store = PaperStore(args.store, starting_cash=Decimal(args.cash))
    store.reset()

    inserted = 0
    for index, symbol in enumerate(SYMBOLS):
        rows = candles(symbol, args.days)
        if len(rows) < 12:
            continue
        # Spread the round trips across the window rather than clustering at the end.
        for trip in range(args.per_symbol):
            hold = HOLD_DAYS[trip % len(HOLD_DAYS)]
            start = trip * 3 + index % 3
            end = start + hold
            if end >= len(rows):
                break
            buy_day, buy_close = rows[start]
            sell_day, sell_close = rows[end]
            quantity = max(1, int(Decimal("4500") / buy_close))
            try:
                store.order(
                    symbol, "buy", quantity, buy_close,
                    at=datetime.fromisoformat(buy_day).replace(
                        hour=15, minute=30, tzinfo=timezone.utc
                    ),
                )
                # A few positions stay open: the journal should show unrealised P&L too.
                if trip == args.per_symbol - 1 and index % 3 == 0:
                    inserted += 1
                    continue
                store.order(
                    symbol, "sell", quantity, sell_close,
                    at=datetime.fromisoformat(sell_day).replace(
                        hour=20, minute=0, tzinfo=timezone.utc
                    ),
                )
                inserted += 2
            except PaperError as exc:
                print(f"  {symbol} trip {trip}: refused — {exc}")
    context.close()

    account = store.account()
    sells = [f for f in account.fills if f.side == "sell" and f.realised is not None]
    wins = [f for f in sells if f.realised > 0]
    realised = sum((f.realised for f in sells), Decimal("0"))
    print(f"\nfills written: {inserted}")
    print(f"closed trades: {len(sells)} | wins {len(wins)} | realised {realised:.2f}")
    print(f"open positions: {len(account.holdings)} | cash {account.cash:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
