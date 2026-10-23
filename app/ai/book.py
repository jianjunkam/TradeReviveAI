"""The book review: what the paper account looks like, and what it implies.

The product does not issue buy or sell instructions — `AGENTS.md` and the PRD both forbid
signals, and a chatbot telling a student "sell NVDA now" is exactly the thing they forbid.
What it *can* do is put the decision in front of the reader with the arithmetic attached:
how much of the book one position is, how long a loser has been open, how far a loss is past
the account's own limit, whether the cash is doing anything.

Two layers, kept apart on purpose:

* `book_flags()` — arithmetic over the account. No model. Same inputs, same output, every
  time, and every flag carries the numbers that produced it.
* `app.ai.analysis.analyse_book()` — one model call that narrates those flags. It cannot
  invent a flag, a price or a target, and it is told not to recommend anything.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

#: A position larger than this share of equity is a concentration question, not a win.
CONCENTRATION = 0.25
#: An unrealised loss this deep, held this long, is where plans usually die.
DEEP_LOSS = -10.0
DEEP_LOSS_DAYS = 10
#: Sitting still for this long with no movement is a decision the trader has not made.
STALE_DAYS = 30
STALE_BAND = 3.0
#: Cash this idle, while positions are open, means the size is not what it looks like.
CASH_DRAG = 0.60


def _days_held(fills: list, symbol: str) -> int | None:
    """Days since the first buy of this symbol, by the oldest fill still plausible."""
    for fill in sorted(fills, key=lambda f: f.at):
        if fill.symbol == symbol and fill.side == "buy":
            try:
                opened = date.fromisoformat(str(fill.at)[:10])
            except ValueError:
                return None
            return max(0, (date.today() - opened).days)
    return None


def book_flags(state: dict, fills: list, starting_cash: float) -> list[dict]:
    """Deterministic observations about the book. Each one names its own arithmetic."""
    flags: list[dict] = []
    positions = state.get("positions") or []

    if not positions:
        flags.append({
            "rule": "EMPTY_BOOK",
            "severity": "info",
            "symbol": None,
            "text": "No open positions: every fill has been closed. There is nothing to review.",
        })
        return flags

    equity = float(state.get("equity") or 0) or starting_cash
    cash = float(state.get("cash") or 0)
    limit = starting_cash * 0.02

    for position in positions:
        symbol = position["symbol"]
        value = float(position.get("market_value") or 0)
        unrealised = float(position.get("unrealised") or 0)
        price = position.get("price")
        cost = position.get("average_cost")
        weight = value / equity * 100 if equity else 0.0
        pnl_pct = ((float(price) - float(cost)) / float(cost) * 100) if price and cost else 0.0
        days = _days_held(fills, symbol)

        if weight >= CONCENTRATION * 100:
            flags.append({
                "rule": "CONCENTRATION",
                "severity": "warn",
                "symbol": symbol,
                "text": (
                    f"{symbol} is {weight:.1f}% of the account (${value:,.2f} of ${equity:,.2f}). "
                    f"A book this concentrated rises and falls with one company."
                ),
            })

        if unrealised <= -limit:
            flags.append({
                "rule": "LOSS_PAST_LIMIT",
                "severity": "warn",
                "symbol": symbol,
                "text": (
                    f"{symbol} is down ${abs(unrealised):,.2f}, past the ${limit:,.2f} "
                    f"(2% of the ${starting_cash:,.0f} start) that this journal counts as an "
                    "oversized loss."
                ),
            })

        if pnl_pct <= DEEP_LOSS and days is not None and days >= DEEP_LOSS_DAYS:
            flags.append({
                "rule": "LOSER_HELD",
                "severity": "warn",
                "symbol": symbol,
                "text": (
                    f"{symbol} is {pnl_pct:.1f}% below its average cost of ${float(cost):,.2f} "
                    f"after {days} days open. The journal's own rule flags losers held past "
                    "two days; this one is far past it."
                ),
            })

        if days is not None and days >= STALE_DAYS and abs(pnl_pct) <= STALE_BAND:
            flags.append({
                "rule": "STALE",
                "severity": "info",
                "symbol": symbol,
                "text": (
                    f"{symbol} has moved {pnl_pct:+.1f}% in {days} days — inside ±{STALE_BAND:.0f}%. "
                    "Open, but not doing anything."
                ),
            })

        if pnl_pct >= 25:
            flags.append({
                "rule": "BIG_WINNER",
                "severity": "info",
                "symbol": symbol,
                "text": (
                    f"{symbol} is up {pnl_pct:.1f}% (${unrealised:,.2f}) at "
                    f"${float(price):,.2f} against a ${float(cost):,.2f} cost."
                ),
            })

    cash_share = cash / equity * 100 if equity else 0.0
    if cash_share >= CASH_DRAG * 100:
        flags.append({
            "rule": "CASH_DRAG",
            "severity": "info",
            "symbol": None,
            "text": (
                f"${cash:,.2f} of the ${equity:,.2f} account is uninvested ({cash_share:.0f}%), "
                "so the book is mostly cash rather than positions."
            ),
        })

    order = {"warn": 0, "info": 1}
    flags.sort(key=lambda f: (order.get(f["severity"], 2), f["symbol"] or ""))
    return flags


def book_summary(state: dict, flags: list[dict], fills: list) -> dict:
    """The small, factual block the model is allowed to see."""
    positions = state.get("positions") or []
    return {
        "cash": state.get("cash"),
        "equity": state.get("equity"),
        "starting_cash": state.get("starting_cash"),
        "invested": state.get("market_value"),
        "unrealised": state.get("unrealised"),
        "open_positions": len(positions),
        "positions": [
            {
                "symbol": p["symbol"],
                "quantity": p.get("quantity"),
                "cost": p.get("average_cost"),
                "price": p.get("price"),
                "market_value": p.get("market_value"),
                "unrealised": p.get("unrealised"),
                "priced": p.get("priced"),
                "days_held": _days_held(fills, p["symbol"]),
            }
            for p in positions
        ],
        "flags": [{"rule": f["rule"], "symbol": f["symbol"], "text": f["text"]} for f in flags],
    }
