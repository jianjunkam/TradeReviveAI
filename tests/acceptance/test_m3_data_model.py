"""Acceptance tests: M3 · the data model itself (docs/DATA_MODEL.md, docs/QUALITY.md).

The features have their own files (F1, F2). These tests are about the schema and the
repository rules underneath every feature:

* every table has a `tenant_id`, `NOT NULL`, indexed — the "every row carries it" rule;
* money is NUMERIC(18,2), so P&L is exact (AGENTS.md);
* the PostgreSQL scope refuses another tenant's row on read, update and delete;
* the migrations are the only thing that created the schema, and they are at head.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Numeric, inspect, text

from app.models import TradingAccount
from app.tenancy import RecordNotFound

TABLES = (
    "users",
    "trading_accounts",
    "trades",
    "mistake_tags",
    "performance_metrics",
    "recovery_reports",
)

MONEY_COLUMNS = ("entry_price", "exit_price", "fees", "gross_pnl", "net_pnl")


def test_every_table_has_a_tenant_id(db_engine):
    """Every row carries the tenant, and every lookup can filter on it."""
    inspector = inspect(db_engine)
    present = set(inspector.get_table_names())
    assert set(TABLES) <= present, f"missing tables: {set(TABLES) - present}"

    for table in TABLES:
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        assert "tenant_id" in columns, f"{table} has no tenant_id"
        assert columns["tenant_id"]["nullable"] is False, f"{table}.tenant_id is nullable"

        indexed = {
            tuple(index["column_names"][:1])
            for index in inspector.get_indexes(table)
            if index["column_names"]
        }
        assert ("tenant_id",) in indexed, f"{table}.tenant_id is not indexed"


def test_money_is_decimal_with_two_places(db_engine):
    """AGENTS.md: Decimal for money, rounded to 2 places. Never a float, never text."""
    columns = {column["name"]: column for column in inspect(db_engine).get_columns("trades")}

    for name in MONEY_COLUMNS:
        column_type = columns[name]["type"]
        assert isinstance(column_type, Numeric), f"trades.{name} is {column_type!r}, not Numeric"
        assert column_type.precision == 18
        assert column_type.scale == 2


def test_migrations_created_the_schema_and_are_at_head(db_engine):
    """The schema comes from Alembic, so a deploy can rebuild it from nothing."""
    with db_engine.connect() as conn:
        revision = conn.execute(text("select version_num from alembic_version")).scalar_one()

    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from pathlib import Path

    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[2] / "migrations")
    )
    head = ScriptDirectory.from_config(config).get_current_head()
    assert revision == head, f"database is at {revision}, migrations head is {head}"


def test_postgres_scope_refuses_another_tenants_row(pg_env):
    """The same rules M2 proved with the in-memory store, now on PostgreSQL."""
    pg_env.register("scope-a@example.com", "A")
    pg_env.register("scope-b@example.com", "B")
    a_tenant = pg_env.store.get_user_by_email("scope-a@example.com").tenant_id
    b_tenant = pg_env.store.get_user_by_email("scope-b@example.com").tenant_id

    a_scope = pg_env.tenancy.scope(a_tenant)
    b_scope = pg_env.tenancy.scope(b_tenant)

    b_row = b_scope.add(
        TradingAccount, id="acct_b", user_id="user_b", broker_name="B", initial_capital=1000
    )

    with pytest.raises(RecordNotFound):
        a_scope.get(TradingAccount, b_row.id)
    with pytest.raises(RecordNotFound):
        a_scope.update(TradingAccount, b_row.id, broker_name="HACKED")
    with pytest.raises(RecordNotFound):
        a_scope.delete(TradingAccount, b_row.id)

    assert b_scope.get(TradingAccount, b_row.id).broker_name == "B"
    assert [row.id for row in a_scope.list(TradingAccount)] == []

    # The scope owns the tenant: a caller cannot hand it a different one.
    smuggled = a_scope.add(TradingAccount, id="acct_a", tenant_id=b_tenant, user_id="user_a")
    assert smuggled.tenant_id == a_tenant
