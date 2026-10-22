"""Acceptance tests: Trade Data Import & Ingestion (use case UC2 in docs/REQUIREMENTS.md)

Used by: Trader (Account Owner). Upload broker CSV files or manually input trades with validation (ticker, side, entry/exit price, size, fees, dates).

Filled in at M3 against PostgreSQL. Money is handled as Decimal and stored as
NUMERIC(18,2) (AGENTS.md), so P&L comparisons are exact, never float.
"""

import pytest

CSV_HEADER = "symbol,action,quantity,entry_price,exit_price,entry_timestamp,exit_timestamp,fees"


def _trade(**overrides):
    payload = {
        "symbol": "NVDA",
        "action": "BUY",
        "quantity": "10",
        "entry_price": "120",
        "exit_price": "126",
        "entry_timestamp": "2026-10-01T09:30:00+08:00",
        "exit_timestamp": "2026-10-01T15:00:00+08:00",
        "fees": "0",
        "emotion": "Breakout",
    }
    payload.update(overrides)
    return payload


def test_ac2_1(pg_env):
    """NVDA 120 -> 126 x 10 is +60.00 gross, on the caller's tenant."""
    user = pg_env.sign_in("trader@example.com")

    response = pg_env.client.post("/trades", json=_trade())

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["gross_pnl"] == "60.00", body
    assert body["tenant_id"] == user.tenant_id
    assert body["symbol"] == "NVDA"
    assert body["emotion"] == "Breakout"

    listed = pg_env.client.get("/trades")
    assert listed.status_code == 200
    rows = listed.json()["trades"]
    assert len(rows) == 1
    assert rows[0]["gross_pnl"] == "60.00"
    assert rows[0]["tenant_id"] == user.tenant_id


def test_ac2_2(pg_env):
    """A CSV with 2 bad rows commits the 20 good ones and reports the bad ones."""
    pg_env.sign_in("importer@example.com")

    rows = [CSV_HEADER]
    for i in range(20):
        rows.append(
            f"AAA{i},BUY,10,100.0,101.0,2026-10-{i + 1:02d}T09:30:00+08:00,"
            f"2026-10-{i + 1:02d}T15:00:00+08:00,0"
        )
    rows.append("BAD1,BUY,-5,100.0,101.0,2026-10-01T09:30:00+08:00,2026-10-01T15:00:00+08:00,0")
    rows.append("BAD2,SELL,-2,100.0,101.0,2026-10-02T09:30:00+08:00,2026-10-02T15:00:00+08:00,0")
    csv_text = "\n".join(rows)

    response = pg_env.client.post(
        "/trades/import", files={"file": ("broker.csv", csv_text, "text/csv")}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] == 20, body
    assert body["rejected"] == 2, body
    assert len(body["errors"]) == 2
    assert {error["row"] for error in body["errors"]} == {21, 22}
    assert all("quantity" in error["reason"].lower() for error in body["errors"])

    stored = pg_env.client.get("/trades").json()["trades"]
    assert len(stored) == 20


def test_ac2_3(pg_env):
    """An exit before the entry is refused with the exact message the pack names."""
    pg_env.sign_in("chrono@example.com")

    response = pg_env.client.post(
        "/trades",
        json=_trade(
            entry_timestamp="2026-10-01T15:00:00+08:00",
            exit_timestamp="2026-10-01T09:30:00+08:00",
        ),
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Exit date cannot precede entry date"
    assert pg_env.client.get("/trades").json()["trades"] == []


def test_ac2_4(pg_env):
    """Re-importing an identical trade skips it: no duplicate, no server error."""
    pg_env.sign_in("dupe@example.com")
    row = "NVDA,BUY,10,120.0,126.0,2026-10-01T09:30:00+08:00,2026-10-01T15:00:00+08:00,0"
    csv_text = f"{CSV_HEADER}\n{row}\n"

    first = pg_env.client.post(
        "/trades/import", files={"file": ("a.csv", csv_text, "text/csv")}
    )
    assert first.status_code == 200
    assert first.json()["imported"] == 1

    second = pg_env.client.post(
        "/trades/import", files={"file": ("b.csv", csv_text, "text/csv")}
    )

    assert second.status_code == 200, second.text
    assert second.json()["imported"] == 0
    assert second.json()["skipped"] == 1
    assert len(pg_env.client.get("/trades").json()["trades"]) == 1


def test_ac2_fees_reduce_net_not_gross(pg_env):
    """Net P&L deducts the fees; gross stays gross (AGENTS.md: Decimal money)."""
    pg_env.sign_in("fees@example.com")

    response = pg_env.client.post("/trades", json=_trade(fees="4.50"))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["gross_pnl"] == "60.00"
    assert body["net_pnl"] == "55.50"


def test_ac2_trades_are_tenant_isolated(pg_env):
    """Two traders never see each other's trades, through the API or the query string."""
    pg_env.sign_in("a@example.com")
    assert pg_env.client.post("/trades", json=_trade(symbol="AAA")).status_code == 201
    a_tenant = pg_env.store.get_user_by_email("a@example.com").tenant_id

    other = pg_env.new_client()
    pg_env.sign_in("b@example.com", other)
    assert other.post("/trades", json=_trade(symbol="BBB")).status_code == 201
    b_tenant = pg_env.store.get_user_by_email("b@example.com").tenant_id
    assert a_tenant != b_tenant

    a_rows = pg_env.client.get("/trades").json()["trades"]
    b_rows = other.get("/trades").json()["trades"]
    assert [row["symbol"] for row in a_rows] == ["AAA"]
    assert [row["symbol"] for row in b_rows] == ["BBB"]

    smuggled = pg_env.client.get("/trades", params={"tenant_id": b_tenant})
    assert smuggled.status_code == 403, smuggled.text
