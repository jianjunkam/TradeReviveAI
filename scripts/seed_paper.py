"""Seed the paper account with trades at real historical closes.

Why historical: a trade opened at today's price has no P&L until tomorrow, so a freshly
seeded journal would be a flat line of zeros. Every fill below is priced from an actual
daily close returned by OpenD — the wins and the losses are what the market did, not what
we wanted the demo to look like.

Run it from the repo root:

    ./.venv/Scripts/python.exe scripts/seed_paper.py --per-symbol 6

It resets the account first, so it is repeatable. Historical K-line quota is 100 requests
per day; one request per symbol covers it.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moomoo import KLType, OpenQuoteContext, RET_OK  # noqa: E402

from app.paper import PaperError, PaperStore  # noqa: E402

SYMBOLS = [
    "US.AAPL", "US.MSFT", "US.NVDA", "US.AMZN", "US.GOOGL",
    "US.META", "US.TSLA", "US.JPM", "US.XOM", "US.KO",
]
HOLD_DAYS = [3, 2, 5, 4, 2, 6]  # deterministic, varied on purpose


def candles(context, symbol: str, days: int) -> list[tuple[str, Decimal]]:
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
    ret, data, _page = context.request_history_kline(
        symbol, start=start, end=end, ktype=KLType.K_DAY, max_count=days
    )
    if ret != RET_OK:
        print(f"  {symbol}: no candles ({data})")
        return []
    rows = []
    for row in data.to_dict("records"):
        close = row.get("close")
        if close is None or float(close) <= 0:
            continue
        rows.append((str(row["time_key"])[:10], Decimal(str(close))))
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

    context = OpenQuoteContext(host="127.0.0.1", port=11111)
    time.sleep(0.5)

    inserted = 0
    for index, symbol in enumerate(SYMBOLS):
        rows = candles(context, symbol, args.days)
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
