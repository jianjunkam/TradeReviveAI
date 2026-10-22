"""Trade import: the quick form and a broker CSV (F2).

Money is `Decimal` end to end and rounded once, to 2 places (AGENTS.md). Validation is
server-side and per row: a bad row is reported, never silently dropped, and one bad row
does not lose the twenty good ones around it.
"""

from __future__ import annotations

import csv
import io
import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError

from app.auth import sessions
from app.models import Trade
from app.permissions import F_IMPORT, permit

router = APIRouter(include_in_schema=False)

PENNY = Decimal("0.01")
EXIT_BEFORE_ENTRY = "Exit date cannot precede entry date"
ACTIONS = ("BUY", "SELL")


class TradeIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    action: str
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    entry_timestamp: datetime
    exit_timestamp: datetime
    fees: Decimal = Decimal("0")
    emotion: str | None = None
    notes: str | None = None
    account_id: str | None = None
    asset_class: str = "Stock"

    @field_validator("action")
    @classmethod
    def _action(cls, value: str) -> str:
        upper = value.strip().upper()
        if upper not in ACTIONS:
            raise ValueError(f"action must be one of {', '.join(ACTIONS)}")
        return upper

    @field_validator("quantity")
    @classmethod
    def _quantity(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("quantity must be greater than zero")
        return value

    @field_validator("entry_price", "exit_price", "fees")
    @classmethod
    def _money(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("money values cannot be negative")
        return value


def _scope(request: Request):
    user = sessions.current_user(request)
    if user is None:  # the guard gets here first; this is the belt-and-braces case
        raise HTTPException(status_code=401, detail="Sign in first.")
    return request.app.state.tenancy.scope(user.tenant_id), user


def _money(value: Decimal) -> Decimal:
    return value.quantize(PENNY, rounding=ROUND_HALF_UP)


def _pnl(payload: TradeIn) -> tuple[Decimal, Decimal]:
    """Gross and net P&L. A SELL profits when the price falls, so direction is -1."""
    direction = Decimal(1) if payload.action == "BUY" else Decimal(-1)
    gross = _money((payload.exit_price - payload.entry_price) * payload.quantity * direction)
    return gross, _money(gross - payload.fees)


def _check_chronology(payload: TradeIn) -> None:
    if payload.exit_timestamp < payload.entry_timestamp:
        raise HTTPException(status_code=400, detail=EXIT_BEFORE_ENTRY)


def _insert(scope, payload: TradeIn) -> Trade:
    gross, net = _pnl(payload)
    return scope.add(
        Trade,
        id=f"trade_{secrets.token_hex(8)}",
        symbol=payload.symbol.strip().upper(),
        action=payload.action,
        asset_class=payload.asset_class,
        account_id=payload.account_id,
        entry_timestamp=payload.entry_timestamp,
        exit_timestamp=payload.exit_timestamp,
        entry_price=payload.entry_price,
        exit_price=payload.exit_price,
        quantity=payload.quantity,
        fees=payload.fees,
        gross_pnl=gross,
        net_pnl=net,
        emotion=payload.emotion,
        notes=payload.notes,
    )


def _out(row: Trade) -> dict:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "symbol": row.symbol,
        "action": row.action,
        "asset_class": row.asset_class,
        "quantity": f"{row.quantity:f}",
        "entry_price": f"{row.entry_price:.2f}",
        "exit_price": f"{row.exit_price:.2f}",
        "fees": f"{row.fees:.2f}",
        "gross_pnl": f"{row.gross_pnl:.2f}",
        "net_pnl": f"{row.net_pnl:.2f}",
        "entry_timestamp": row.entry_timestamp.isoformat(),
        "exit_timestamp": row.exit_timestamp.isoformat(),
        "emotion": row.emotion,
    }


@router.get("/trades")
@permit(F_IMPORT, sign_in_required=True)
def list_trades(request: Request) -> dict:
    scope, _ = _scope(request)
    rows = scope.list(Trade, order_by=Trade.entry_timestamp)
    return {"trades": [_out(row) for row in rows]}


@router.post("/trades", status_code=201)
@permit(F_IMPORT, sign_in_required=True)
def create_trade(request: Request, payload: TradeIn) -> dict:
    scope, _ = _scope(request)
    _check_chronology(payload)
    try:
        row = _insert(scope, payload)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="That trade already exists in your journal."
        ) from exc
    return _out(row)


@router.post("/trades/import")
@permit(F_IMPORT, sign_in_required=True)
async def import_trades(request: Request, file: UploadFile = File(...)) -> dict:
    """Import a broker CSV. Good rows are committed; each bad row is reported by number."""
    scope, _ = _scope(request)
    raw = (await file.read()).decode("utf-8-sig", errors="replace")

    reader = csv.DictReader(io.StringIO(raw))
    required = {
        "symbol",
        "action",
        "quantity",
        "entry_price",
        "exit_price",
        "entry_timestamp",
        "exit_timestamp",
    }
    missing = required - set(reader.fieldnames or [])
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"The CSV is missing these columns: {', '.join(sorted(missing))}",
        )

    imported = 0
    skipped = 0
    errors: list[dict] = []

    for row_number, raw_row in enumerate(reader, start=1):
        try:
            payload = TradeIn(
                symbol=raw_row.get("symbol") or "",
                action=raw_row.get("action") or "",
                quantity=Decimal((raw_row.get("quantity") or "").strip()),
                entry_price=Decimal((raw_row.get("entry_price") or "").strip()),
                exit_price=Decimal((raw_row.get("exit_price") or "").strip()),
                fees=Decimal((raw_row.get("fees") or "0").strip() or "0"),
                entry_timestamp=datetime.fromisoformat(
                    (raw_row.get("entry_timestamp") or "").strip()
                ),
                exit_timestamp=datetime.fromisoformat(
                    (raw_row.get("exit_timestamp") or "").strip()
                ),
                emotion=(raw_row.get("emotion") or None),
            )
        except (InvalidOperation, ValueError) as exc:
            errors.append({"row": row_number, "reason": _reason(exc)})
            continue

        if payload.exit_timestamp < payload.entry_timestamp:
            errors.append({"row": row_number, "reason": EXIT_BEFORE_ENTRY})
            continue

        try:
            _insert(scope, payload)
            imported += 1
        except IntegrityError:
            # AC2.4: the same trade twice is one trade, not an error page.
            skipped += 1

    return {
        "imported": imported,
        "skipped": skipped,
        "rejected": len(errors),
        "errors": errors,
    }


def _reason(exc: Exception) -> str:
    """A short, row-level reason a beginner trader can act on."""
    if isinstance(exc, InvalidOperation):
        return "a numeric field held something that is not a number"
    text = str(exc)
    if "quantity" in text.lower():
        return "quantity must be greater than zero"
    return text.splitlines()[0][:200] if text else "the row could not be read"
