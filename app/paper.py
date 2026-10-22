"""Paper trading: a simulated account that fills at real market prices.

Two hard rules:

* **No real order is ever placed.** Nothing here talks to a trading context; it writes to a
  local JSON file. The UI says "simulated" everywhere, because a paper P&L that looks like
  a real one is how people talk themselves into real money.
* **No fill without a real price.** The caller must pass the price the broker just
  reported. If the broker is unreachable the order is refused, never filled at a guess.

Money is `Decimal`, quantised to two places — the same rule the trade ledger follows.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

CENT = Decimal("0.01")


class PaperError(RuntimeError):
    """The order was refused. The message is shown to the user as written."""


def _money(value: Decimal | str | float) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class Holding:
    symbol: str
    quantity: int
    average_cost: Decimal

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "average_cost": float(self.average_cost),
        }


@dataclass
class Fill:
    id: str
    at: str
    symbol: str
    side: str
    quantity: int
    price: Decimal
    cash_after: Decimal
    realised: Decimal | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "at": self.at,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": float(self.price),
            "cash_after": float(self.cash_after),
            "realised": None if self.realised is None else float(self.realised),
        }


@dataclass
class PaperAccount:
    """One simulated account. Single-account on purpose: this is a local demo."""

    starting_cash: Decimal = Decimal("100000.00")
    cash: Decimal = field(default_factory=lambda: Decimal("100000.00"))
    holdings: dict[str, Holding] = field(default_factory=dict)
    realised: Decimal = Decimal("0.00")
    fills: list[Fill] = field(default_factory=list)

    # ------------------------------------------------------------------ orders

    def buy(self, symbol: str, quantity: int, price: Decimal, at: datetime | None = None) -> Fill:
        symbol = symbol.strip().upper()
        if not symbol.startswith("US."):
            raise PaperError(
                f"{symbol} is not a US stock code. Paper trading here covers US stocks only, "
                "for example US.AAPL."
            )
        if quantity <= 0:
            raise PaperError("Quantity must be a whole number of shares, at least 1.")
        price = _money(price)
        if price <= 0:
            raise PaperError("Refusing to fill at a price of zero.")

        cost = _money(price * quantity)
        if cost > self.cash:
            raise PaperError(
                f"Not enough cash: {quantity} × ${price} = ${cost}, but only "
                f"${self.cash} is available."
            )

        self.cash = _money(self.cash - cost)
        held = self.holdings.get(symbol)
        if held is None:
            self.holdings[symbol] = Holding(symbol=symbol, quantity=quantity, average_cost=price)
        else:
            total = _money(held.average_cost * held.quantity + cost)
            held.quantity += quantity
            held.average_cost = _money(total / held.quantity)

        fill = Fill(
            id=uuid.uuid4().hex[:12],
            at=(at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
            symbol=symbol,
            side="buy",
            quantity=quantity,
            price=price,
            cash_after=self.cash,
        )
        self.fills.insert(0, fill)
        return fill

    def sell(self, symbol: str, quantity: int, price: Decimal, at: datetime | None = None) -> Fill:
        symbol = symbol.strip().upper()
        if quantity <= 0:
            raise PaperError("Quantity must be a whole number of shares, at least 1.")
        held = self.holdings.get(symbol)
        if held is None or held.quantity <= 0:
            raise PaperError(f"You do not hold {symbol}, so there is nothing to sell.")
        if quantity > held.quantity:
            raise PaperError(
                f"You hold {held.quantity} share(s) of {symbol}; selling {quantity} would "
                "be a short position, which this demo does not model."
            )
        price = _money(price)
        if price <= 0:
            raise PaperError("Refusing to fill at a price of zero.")

        proceeds = _money(price * quantity)
        realised = _money((price - held.average_cost) * quantity)
        self.cash = _money(self.cash + proceeds)
        held.quantity -= quantity
        if held.quantity == 0:
            del self.holdings[symbol]
        self.realised = _money(self.realised + realised)

        fill = Fill(
            id=uuid.uuid4().hex[:12],
            at=(at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
            symbol=symbol,
            side="sell",
            quantity=quantity,
            price=price,
            cash_after=self.cash,
            realised=realised,
        )
        self.fills.insert(0, fill)
        return fill

    # ------------------------------------------------------------------- state

    def state(self, marks: dict[str, float] | None = None) -> dict:
        """Account state. `marks` are live prices; a holding without one is marked at cost."""
        marks = marks or {}
        positions = []
        market_value = Decimal("0.00")
        unrealised_total = Decimal("0.00")
        for held in sorted(self.holdings.values(), key=lambda h: h.symbol):
            mark = marks.get(held.symbol)
            price = _money(mark) if mark else held.average_cost
            value = _money(price * held.quantity)
            unrealised = _money((price - held.average_cost) * held.quantity)
            market_value = _money(market_value + value)
            unrealised_total = _money(unrealised_total + unrealised)
            positions.append(
                {
                    **held.as_dict(),
                    "price": float(price),
                    "market_value": float(value),
                    "unrealised": float(unrealised),
                    "priced": bool(mark),
                }
            )

        equity = _money(self.cash + market_value)
        return {
            "starting_cash": float(self.starting_cash),
            "cash": float(self.cash),
            "market_value": float(market_value),
            "equity": float(equity),
            "realised": float(self.realised),
            "unrealised": float(unrealised_total),
            "total_return": float(_money(equity - self.starting_cash)),
            "positions": positions,
            "fills": [fill.as_dict() for fill in self.fills[:25]],
            "simulated": True,
        }

    # ------------------------------------------------------------ persistence

    def to_json(self) -> dict:
        return {
            "starting_cash": str(self.starting_cash),
            "cash": str(self.cash),
            "realised": str(self.realised),
            "holdings": [
                {"symbol": h.symbol, "quantity": h.quantity, "average_cost": str(h.average_cost)}
                for h in self.holdings.values()
            ],
            "fills": [
                {
                    "id": f.id,
                    "at": f.at,
                    "symbol": f.symbol,
                    "side": f.side,
                    "quantity": f.quantity,
                    "price": str(f.price),
                    "cash_after": str(f.cash_after),
                    "realised": None if f.realised is None else str(f.realised),
                }
                for f in self.fills[:200]
            ],
        }

    @classmethod
    def from_json(cls, payload: dict, starting_cash: Decimal) -> "PaperAccount":
        account = cls(starting_cash=starting_cash, cash=_money(payload["cash"]))
        account.realised = _money(payload.get("realised", "0"))
        for row in payload.get("holdings", []):
            try:
                account.holdings[row["symbol"]] = Holding(
                    symbol=row["symbol"],
                    quantity=int(row["quantity"]),
                    average_cost=_money(row["average_cost"]),
                )
            except (KeyError, InvalidOperation, ValueError):
                continue
        for row in payload.get("fills", []):
            try:
                account.fills.append(
                    Fill(
                        id=str(row["id"]),
                        at=str(row["at"]),
                        symbol=str(row["symbol"]),
                        side=str(row["side"]),
                        quantity=int(row["quantity"]),
                        price=_money(row["price"]),
                        cash_after=_money(row["cash_after"]),
                        realised=None if row.get("realised") is None else _money(row["realised"]),
                    )
                )
            except (KeyError, InvalidOperation, ValueError):
                continue
        return account


class PaperStore:
    """The account, plus a JSON file so a restart does not wipe the demo."""

    def __init__(self, path: str | Path, starting_cash: Decimal = Decimal("100000.00")) -> None:
        self._path = Path(path)
        self._starting_cash = _money(starting_cash)
        self._lock = threading.Lock()
        self._account = self._load()

    def _load(self) -> PaperAccount:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return PaperAccount(
                starting_cash=self._starting_cash, cash=self._starting_cash
            )
        account = PaperAccount.from_json(payload, self._starting_cash)
        account.starting_cash = _money(payload.get("starting_cash", self._starting_cash))
        return account

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._account.to_json(), indent=2)
        handle, temp = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(payload)
            os.replace(temp, self._path)
        except Exception:  # noqa: BLE001 - a failed save must not lose the order
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise

    def account(self) -> PaperAccount:
        with self._lock:
            return self._account

    def order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: Decimal,
        at: datetime | None = None,
    ) -> Fill:
        side = side.strip().lower()
        if side not in {"buy", "sell"}:
            raise PaperError("Side must be 'buy' or 'sell'.")
        with self._lock:
            fill = (
                self._account.buy(symbol, quantity, price, at=at)
                if side == "buy"
                else self._account.sell(symbol, quantity, price, at=at)
            )
            self._save()
            return fill

    def reset(self) -> PaperAccount:
        with self._lock:
            self._account = PaperAccount(
                starting_cash=self._starting_cash, cash=self._starting_cash
            )
            self._save()
            return self._account
