"""The trade journal, computed from the paper account's fills.

This replaced a hand-written sample. Every figure below is arithmetic over real fills at
real historical prices — including the losing ones. Where there is not enough data the
answer is `null`, and the page says so rather than showing a zero that looks like a fact.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request

from app.paper import Fill
from app.permissions import public

router = APIRouter(prefix="/api/journal", include_in_schema=False)


def _day(stamp: str) -> str:
    return str(stamp)[:10]


def _marks(request: Request) -> dict[str, float]:
    cache = request.app.state.market
    store = request.app.state.paper
    if cache is None:
        return {}
    rows = {row.symbol: row.last_price for row in cache.snapshot().rows}
    return {s: rows[s] for s in store.account().holdings if rows.get(s)}


def _holding_days(fills: list[Fill]) -> dict[str, int]:
    """FIFO: the age in days of the shares each sell closed."""
    open_lots: dict[str, list[tuple[str, int]]] = {}
    ages: dict[str, int] = {}
    for fill in fills:
        if fill.side == "buy":
            open_lots.setdefault(fill.symbol, []).append((_day(fill.at), fill.quantity))
            continue
        remaining = fill.quantity
        while remaining > 0 and open_lots.get(fill.symbol):
            bought_day, qty = open_lots[fill.symbol][0]
            used = min(qty, remaining)
            try:
                days = (
                    datetime.fromisoformat(_day(fill.at))
                    - datetime.fromisoformat(bought_day)
                ).days
            except ValueError:
                days = 0
            ages[fill.id] = max(ages.get(fill.id, 0), days)
            remaining -= used
            if used == qty:
                open_lots[fill.symbol].pop(0)
            else:
                open_lots[fill.symbol][0] = (bought_day, qty - used)
    return ages


@router.get("/summary")
@public
def summary(request: Request) -> dict:
    if not request.app.state.settings.public_dashboard:
        raise HTTPException(status_code=404, detail="Not found.")

    account = request.app.state.paper.account()
    state = account.state(_marks(request))
    fills = sorted(account.fills, key=lambda f: f.at)
    sells = [f for f in fills if f.side == "sell" and f.realised is not None]
    ages = _holding_days(fills)

    wins = [f for f in sells if (f.realised or 0) > 0]
    losses = [f for f in sells if (f.realised or 0) < 0]
    gross_win = sum((f.realised or Decimal(0)) for f in wins)
    gross_loss = -sum((f.realised or Decimal(0)) for f in losses)

    # Equity after each closed trade, then today's mark, so the curve ends where the
    # account actually is.
    curve: list[dict] = []
    running = account.starting_cash
    for fill in sells:
        running += fill.realised or Decimal(0)
        curve.append({"date": _day(fill.at), "value": round(float(running), 2)})
    curve.append({"date": datetime.now().strftime("%Y-%m-%d"), "value": round(float(state["equity"]), 2)})

    peak = -1e18
    worst_dd = 0.0
    peak_at = trough_at = None
    for point in curve:
        if point["value"] > peak:
            peak = point["value"]
            peak_at = point["date"]
        drop = peak - point["value"]
        if drop > worst_dd:
            worst_dd = drop
            trough_at = point["date"]

    daily: dict[str, float] = {}
    for fill in sells:
        daily[_day(fill.at)] = round(daily.get(_day(fill.at), 0.0) + float(fill.realised or 0), 2)

    # Rules are behaviours, not outcomes. Losing money is not a mistake — every strategy
    # does. What is measurable and fixable: losses that blew past a limit, exits made
    # before the plan could play out, days with more trades than judgement, and symbols
    # traded so often that fees and noise dominate.
    threshold = account.starting_cash * Decimal("0.02")

    oversized = [f for f in losses if abs(f.realised or 0) > threshold]
    oversized_cost = sum((abs(f.realised or 0) - threshold) for f in oversized)

    quick = [f for f in losses if ages.get(f.id, 99) <= 2]
    quick_cost = -sum((f.realised or 0) for f in quick)

    by_day: dict[str, list[Fill]] = {}
    for fill in sells:
        by_day.setdefault(_day(fill.at), []).append(fill)
    busy_days = {d: fs for d, fs in by_day.items() if len(fs) >= 3}
    overtrade_cost = -sum(
        (min(Decimal(0), sum((f.realised or 0) for f in fs)) for fs in busy_days.values()),
        Decimal(0),
    )

    by_symbol: dict[str, list[Fill]] = {}
    for fill in sells:
        by_symbol.setdefault(fill.symbol, []).append(fill)
    churned = {s: fs for s, fs in by_symbol.items() if len(fs) >= 4}
    churn_cost = -sum(
        (min(Decimal(0), sum((f.realised or 0) for f in fs)) for fs in churned.values()),
        Decimal(0),
    )

    mistakes = [
        {
            "rule": "OVERSIZED_LOSS",
            "label": "Loss beyond 2%",
            "note": f"Single trades losing more than ${float(threshold):,.0f}. "
                    "Counted at the amount past the limit, not the whole loss.",
            "count": len(oversized),
            "cost": round(float(oversized_cost), 2),
        },
        {
            "rule": "QUICK_LOSS_EXIT",
            "label": "Cut within two days",
            "note": "Losers closed within two days of entry — the plan never had time to work.",
            "count": len(quick),
            "cost": round(float(quick_cost), 2),
        },
        {
            "rule": "OVERTRADING",
            "label": "Three or more exits in a day",
            "note": f"{len(busy_days)} day(s) with three or more closed trades, counted where that day lost money.",
            "count": len(busy_days),
            "cost": round(float(overtrade_cost), 2),
        },
        {
            "rule": "CHURNED_SYMBOL",
            "label": "Same symbol, four or more round trips",
            "note": f"{len(churned)} symbol(s) traded repeatedly, counted where the symbol lost money overall.",
            "count": len(churned),
            "cost": round(float(churn_cost), 2),
        },
    ]
    mistakes.sort(key=lambda m: m["cost"], reverse=True)

    trade_count = len(sells)
    win_rate = (len(wins) / trade_count * 100) if trade_count else None
    profit_factor = (float(gross_win) / float(gross_loss)) if gross_loss > 0 else None
    avg_win = (float(gross_win) / len(wins)) if wins else None
    avg_loss = (float(gross_loss) / len(losses)) if losses else None

    if trade_count == 0:
        verdict = "No closed trades yet. Place a few papertrades and the journal fills itself in."
    elif profit_factor is None:
        verdict = f"No losing trade yet across {trade_count} closed trades, so the profit factor is undefined."
    else:
        worst = mistakes[0]
        verdict = (
            f"{trade_count} closed trades, {len(wins)} won. Average win "
            f"${avg_win:,.2f} against an average loss of ${avg_loss:,.2f} gives a profit factor "
            f"of {profit_factor:.2f}"
            + (", so wins outweigh losses." if profit_factor >= 1 else ", so losses outweigh wins.")
            + (
                f" The costliest habit is {worst['label'].lower()} "
                f"({worst['count']}×, ${worst['cost']:,.2f})."
                if worst["cost"] > 0
                else " No rule fired on this sample."
            )
        )

    return {
        "source": "paper",
        "simulated": True,
        "closed_trades": trade_count,
        "open_positions": len(state["positions"]),
        "starting_cash": state["starting_cash"],
        "cash": state["cash"],
        "equity": state["equity"],
        "net_pl": state["total_return"],
        "return_pct": round(state["total_return"] / state["starting_cash"] * 100, 2)
        if state["starting_cash"]
        else None,
        "realised": state["realised"],
        "unrealised": state["unrealised"],
        "win_rate": round(win_rate, 1) if win_rate is not None else None,
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "avg_win": round(avg_win, 2) if avg_win is not None else None,
        "avg_loss": round(avg_loss, 2) if avg_loss is not None else None,
        "best": round(max((float(f.realised or 0) for f in sells), default=0.0), 2) if sells else None,
        "worst": round(min((float(f.realised or 0) for f in sells), default=0.0), 2) if sells else None,
        "max_drawdown": round(worst_dd, 2),
        "max_drawdown_pct": round(worst_dd / peak * 100, 2) if peak > 0 else None,
        "peak_at": peak_at,
        "trough_at": trough_at,
        "equity_curve": curve,
        "daily": [{"date": d, "pl": v} for d, v in sorted(daily.items())],
        "mistakes": mistakes,
        "verdict": verdict,
        "positions": state["positions"],
    }
