"""Paper trading: simulated money, real prices, and refusals that say why.

The rules that matter here are the ones a fake-looking demo usually gets wrong: never fill
without a price, never allow a short position by accident, and never let the numbers drift
from the arithmetic.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.broker.base import MarketRow, Quote, SymbolInfo
from app.broker.fake import FakeBroker
from app.config import Settings
from app.main import create_app
from app.market import MarketCache
from app.paper import PaperAccount, PaperError, PaperStore


def _quote(price: float) -> Quote:
    return Quote(
        symbol="US.AAPL",
        name="Apple",
        last_price=price,
        previous_close=price - 5,
        change_rate=1.32,
        volume=1_000_000,
        bid=price - 0.05,
        ask=price + 0.05,
        updated_at="2026-10-22 15:00:00",
        delayed=False,
        source="fake",
    )


def _row(price: float) -> MarketRow:
    return MarketRow(
        symbol="US.AAPL",
        name="Apple",
        last_price=price,
        previous_close=price - 5,
        change_rate=1.32,
        volume=1_000_000,
        turnover=price * 1_000_000,
        market_cap=5.02e12,
        pe_ratio=30.0,
        bid=price - 0.05,
        ask=price + 0.05,
        updated_at="2026-10-22 15:00:00",
    )


# ------------------------------------------------------------------ the engine


def test_a_buy_moves_cash_into_a_position():
    account = PaperAccount(starting_cash=Decimal("100000.00"), cash=Decimal("100000.00"))

    fill = account.buy("US.AAPL", 10, Decimal("343.99"))

    assert fill.price == Decimal("343.99")
    assert account.cash == Decimal("96560.10")
    assert account.holdings["US.AAPL"].quantity == 10
    assert account.holdings["US.AAPL"].average_cost == Decimal("343.99")


def test_a_second_buy_averages_the_cost():
    account = PaperAccount(starting_cash=Decimal("100000.00"), cash=Decimal("100000.00"))

    account.buy("US.AAPL", 10, Decimal("100.00"))
    account.buy("US.AAPL", 10, Decimal("120.00"))

    assert account.holdings["US.AAPL"].quantity == 20
    assert account.holdings["US.AAPL"].average_cost == Decimal("110.00")


def test_a_sell_realises_profit_and_returns_cash():
    account = PaperAccount(starting_cash=Decimal("100000.00"), cash=Decimal("100000.00"))
    account.buy("US.AAPL", 10, Decimal("343.99"))

    fill = account.sell("US.AAPL", 4, Decimal("400.00"))

    assert fill.realised == Decimal("224.04")  # (400.00 − 343.99) × 4
    assert account.cash == Decimal("98160.10")
    assert account.holdings["US.AAPL"].quantity == 6
    assert account.realised == Decimal("224.04")


def test_selling_the_whole_position_removes_it():
    account = PaperAccount(starting_cash=Decimal("1000.00"), cash=Decimal("1000.00"))
    account.buy("US.AAPL", 2, Decimal("100.00"))

    account.sell("US.AAPL", 2, Decimal("110.00"))

    assert "US.AAPL" not in account.holdings
    assert account.cash == Decimal("1020.00")


def test_you_cannot_spend_cash_you_do_not_have():
    account = PaperAccount(starting_cash=Decimal("100.00"), cash=Decimal("100.00"))

    with pytest.raises(PaperError) as error:
        account.buy("US.AAPL", 1, Decimal("343.99"))

    assert "Not enough cash" in str(error.value)
    assert account.cash == Decimal("100.00")
    assert account.holdings == {}


def test_you_cannot_sell_shares_you_do_not_hold():
    account = PaperAccount(starting_cash=Decimal("100000.00"), cash=Decimal("100000.00"))
    account.buy("US.AAPL", 3, Decimal("100.00"))

    with pytest.raises(PaperError) as error:
        account.sell("US.AAPL", 4, Decimal("100.00"))

    assert "short position" in str(error.value)
    assert account.holdings["US.AAPL"].quantity == 3


def test_a_symbol_outside_the_us_market_is_refused():
    account = PaperAccount(starting_cash=Decimal("100000.00"), cash=Decimal("100000.00"))

    with pytest.raises(PaperError) as error:
        account.buy("MY.5225", 1, Decimal("10.00"))

    assert "US stock code" in str(error.value)


def test_a_quantity_below_one_is_refused():
    account = PaperAccount(starting_cash=Decimal("100000.00"), cash=Decimal("100000.00"))

    with pytest.raises(PaperError):
        account.buy("US.AAPL", 0, Decimal("100.00"))


def test_state_marks_positions_at_the_given_price():
    account = PaperAccount(starting_cash=Decimal("10000.00"), cash=Decimal("10000.00"))
    account.buy("US.AAPL", 10, Decimal("100.00"))

    state = account.state({"US.AAPL": 120.0})

    assert state["cash"] == 9000.0
    assert state["market_value"] == 1200.0
    assert state["equity"] == 10200.0
    assert state["unrealised"] == 200.0
    assert state["total_return"] == 200.0
    assert state["simulated"] is True


def test_state_admits_when_a_position_has_no_mark():
    """Without a live price the holding is valued at cost, and says so."""
    account = PaperAccount(starting_cash=Decimal("10000.00"), cash=Decimal("10000.00"))
    account.buy("US.AAPL", 10, Decimal("100.00"))

    position = account.state({})["positions"][0]

    assert position["priced"] is False
    assert position["price"] == 100.0


# --------------------------------------------------------------- persistence


def test_the_account_survives_a_restart(tmp_path):
    path = tmp_path / "paper.json"
    store = PaperStore(path, starting_cash=Decimal("100000.00"))
    store.order("US.AAPL", "buy", 5, Decimal("200.00"))

    reloaded = PaperStore(path, starting_cash=Decimal("100000.00"))

    assert reloaded.account().holdings["US.AAPL"].quantity == 5
    assert reloaded.account().cash == Decimal("99000.00")
    assert len(reloaded.account().fills) == 1


def test_reset_returns_to_the_starting_cash(tmp_path):
    store = PaperStore(tmp_path / "paper.json", starting_cash=Decimal("50000.00"))
    store.order("US.AAPL", "buy", 1, Decimal("100.00"))

    account = store.reset()

    assert account.cash == Decimal("50000.00")
    assert account.holdings == {}
    assert account.fills == []


# ------------------------------------------------------------------- the API


def _client(tmp_path, *, connected: bool = True, mark: float = 400.0):
    broker = FakeBroker(
        connected=connected,
        reason="OpenD is not listening on 127.0.0.1:11111" if not connected else None,
        quotes={"US.AAPL": _quote(343.99)},
        rows=[_row(mark)],
        universe=[SymbolInfo(symbol="US.AAPL", name="Apple", exchange="NASDAQ")],
    )
    # A warmed cache: positions are marked from the market, not from the fill price.
    cache = MarketCache(broker)
    cache.refresh()
    app = create_app(
        settings=Settings(
            app_secret="test-only",
            environment="development",
            public_dashboard=True,
            paper_store_path=str(tmp_path / "paper.json"),
            paper_starting_cash=100000.0,
        ),
        broker=broker,
        market=cache,
        paper=PaperStore(tmp_path / "paper.json", starting_cash=Decimal("100000.00")),
    )
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def test_paper_endpoints_are_closed_when_the_dashboard_is_off(tmp_path):
    app = create_app(
        settings=Settings(app_secret="test-only", environment="development", demo_closed=True),
        broker=FakeBroker(),
        market=MarketCache(FakeBroker()),
        paper=PaperStore(tmp_path / "paper.json"),
    )
    client = TestClient(app, base_url="https://testserver", follow_redirects=False)

    assert client.get("/api/paper/account").status_code == 404
    assert client.post("/api/paper/order", json={"symbol": "US.AAPL", "side": "buy", "quantity": 1}).status_code == 404


def test_an_order_fills_at_the_broker_price(tmp_path):
    client = _client(tmp_path)

    response = client.post(
        "/api/paper/order", json={"symbol": "US.AAPL", "side": "buy", "quantity": 10}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["fill"]["price"] == 343.99
    assert body["account"]["cash"] == 96560.10
    # Marked from the market cache, not from the fill price.
    assert body["account"]["market_value"] == 4000.0
    assert body["account"]["total_return"] == 560.10


def test_an_oversell_is_refused_with_a_reason(tmp_path):
    client = _client(tmp_path)

    response = client.post(
        "/api/paper/order", json={"symbol": "US.AAPL", "side": "sell", "quantity": 5}
    )

    assert response.status_code == 400
    assert "do not hold" in response.json()["detail"]


def test_no_fill_happens_when_the_broker_is_down(tmp_path):
    client = _client(tmp_path, connected=False)

    response = client.post(
        "/api/paper/order", json={"symbol": "US.AAPL", "side": "buy", "quantity": 1}
    )

    assert response.status_code == 503
    assert "11111" in response.json()["detail"]
    # And the account is untouched.
    assert client.get("/api/paper/account").json()["positions"] == []


def test_the_paper_page_is_served(tmp_path):
    response = _client(tmp_path).get("/papertrade")

    assert response.status_code == 200
    assert "Simulated account" in response.text
    assert 'id="order-form"' in response.text
    assert "/static/papertrade.js" in response.text
