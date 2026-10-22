"""The data model from docs/DATA_MODEL.md, as SQLAlchemy tables.

Two deliberate choices, both driven by a rule rather than taste:

* Money is `NUMERIC(18,2)` and annotated `Decimal`, because AGENTS.md says "use Decimal
  for money and round to 2 decimal places". docs/DATA_MODEL.md calls every field a
  string; storing money as text would make the arithmetic unsafe.
* Timestamps are `timestamptz`, so two traders in different time zones cannot shift each
  other's data.

Every table carries `tenant_id`, `NOT NULL` and indexed. That is not decoration: every
query in `app/repositories.py` filters on it.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.auth.store import TRADER

MONEY = Numeric(18, 2)
QUANTITY = Numeric(18, 4)
PERCENT = Numeric(9, 4)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_tenant_email", "tenant_id", "email"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(64), nullable=False, default=TRADER)
    # docs/DATA_MODEL.md lists it; AGENTS.md forbids storing a password, so it stays NULL.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The doc's language_preference_EN_BM.
    language_preference: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    subscription_tier: Mapped[str] = mapped_column(String(32), nullable=False, default="free")
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="magic_link")
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TradingAccount(Base):
    __tablename__ = "trading_accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    broker_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    account_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="MYR")
    initial_capital: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    current_balance: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (
        # AC2.4: the same trade twice is one trade. The database enforces it, so a race
        # between two imports cannot create a duplicate that the check missed.
        UniqueConstraint(
            "tenant_id",
            "symbol",
            "action",
            "quantity",
            "entry_timestamp",
            "exit_timestamp",
            "entry_price",
            "exit_price",
            name="uq_trades_natural_key",
        ),
        Index("ix_trades_tenant_symbol", "tenant_id", "symbol"),
        Index("ix_trades_tenant_exit", "tenant_id", "exit_timestamp"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(16), nullable=False, default="Stock")
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    entry_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    exit_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    entry_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    exit_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    fees: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    gross_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    net_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    # UC2 step 3 asks for an "emotional entry tag"; DATA_MODEL has no column for it.
    emotion: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MistakeTag(Base):
    __tablename__ = "mistake_tags"
    __table_args__ = (Index("ix_mistake_tags_tenant_rule", "tenant_id", "rule_code"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trade_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_code: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="MEDIUM")
    financial_impact: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PerformanceMetric(Base):
    __tablename__ = "performance_metrics"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    win_rate: Mapped[Decimal] = mapped_column(PERCENT, nullable=False, default=0)
    profit_factor: Mapped[Decimal | None] = mapped_column(PERCENT, nullable=True)
    max_drawdown_pct: Mapped[Decimal] = mapped_column(PERCENT, nullable=False, default=0)
    total_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_fees_paid: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)


class RecoveryReport(Base):
    __tablename__ = "recovery_reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    report_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    executive_summary: Mapped[str] = mapped_column(Text(), nullable=False, default="")
    diagnosed_weaknesses_json: Mapped[str] = mapped_column(Text(), nullable=False, default="[]")
    action_drills_json: Mapped[str] = mapped_column(Text(), nullable=False, default="[]")
    model_used: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
