"""The paper book review: the arithmetic must be ours, and the model must not give orders.

These tests do not call a provider. They pin what the flags say, what the prompt is allowed
to contain, and the refusal to turn "this position is 43% of your account" into "sell it".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.ai.analysis import analyse_book, build_book_prompt
from app.ai.book import book_flags, book_summary
from app.broker.fake import FakeBroker
from app.config import Settings
from app.main import create_app
from app.market import MarketCache
from app.paper import Fill


def _state(positions, cash=10000.0, equity=50000.0):
    return {
        "starting_cash": 100000.0,
        "cash": cash,
        "market_value": equity - cash,
        "equity": equity,
        "unrealised": sum(p["unrealised"] for p in positions),
        "positions": positions,
    }


def _position(symbol, qty, cost, price, days_ago=None):
    value = round(price * qty, 2)
    return {
        "symbol": symbol,
        "quantity": qty,
        "average_cost": cost,
        "price": price,
        "market_value": value,
        "unrealised": round((price - cost) * qty, 2),
        "priced": True,
        "opened_at": None,
    }


def _fills(symbol, days_ago):
    when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return Fill(id="f1", at=when, symbol=symbol, side="buy", quantity=10,
                price=Decimal("100"), cash_after=Decimal("99000"), realised=None)


def test_an_empty_book_says_so_and_returns_nothing_else():
    flags = book_flags(_state([], cash=50000.0, equity=50000.0), [], 100000.0)

    assert len(flags) == 1
    assert flags[0]["rule"] == "EMPTY_BOOK"


def test_a_position_bigger_than_a_quarter_of_the_account_is_flagged():
    # 45,000 of a 50,000 account
    position = _position("US.NVDA", 450, 90.0, 100.0)

    flags = book_flags(_state([position], cash=5000.0, equity=50000.0), [_fills("US.NVDA", 3)], 100000.0)

    concentration = next(f for f in flags if f["rule"] == "CONCENTRATION")
    assert concentration["symbol"] == "US.NVDA"
    assert "90.0% of the account" in concentration["text"]


def test_a_loss_past_the_accounts_own_limit_is_quoted_with_the_limit():
    # 1,000 shares losing $2.50 each = $2,500, past the $2,000 limit
    position = _position("US.KO", 1000, 60.0, 57.5)

    flags = book_flags(_state([position], cash=40000.0, equity=50000.0), [_fills("US.KO", 4)], 100000.0)

    flagged = next(f for f in flags if f["rule"] == "LOSS_PAST_LIMIT")
    assert "$2,500.00" in flagged["text"]
    assert "$2,000.00" in flagged["text"]


def test_a_loser_held_past_two_days_is_flagged_with_its_age():
    position = _position("US.META", 20, 300.0, 240.0)   # -20%

    flags = book_flags(_state([position], cash=40000.0, equity=50000.0), [_fills("US.META", 21)], 100000.0)

    held = next(f for f in flags if f["rule"] == "LOSER_HELD")
    assert "-20.0%" in held["text"]
    assert "21 days" in held["text"]


def test_a_dead_position_is_called_stale_not_a_failure():
    position = _position("US.XOM", 100, 100.0, 101.0)   # +1%

    flags = book_flags(_state([position], cash=40000.0, equity=50000.0), [_fills("US.XOM", 45)], 100000.0)

    stale = next(f for f in flags if f["rule"] == "STALE")
    assert "45 days" in stale["text"]


def test_warnings_come_before_observations():
    positions = [
        _position("US.AAPL", 400, 100.0, 100.5),    # 80% of the book -> warn
        _position("US.XOM", 100, 100.0, 101.0),
    ]

    flags = book_flags(_state(positions, cash=5000.0, equity=50000.0), [_fills("US.XOM", 45)], 100000.0)

    severities = [f["severity"] for f in flags]
    assert severities == sorted(severities, key=lambda s: 0 if s == "warn" else 1)


def test_the_prompt_forbids_orders_and_carries_the_facts():
    positions = [_position("US.NVDA", 450, 90.0, 100.0)]
    flags = book_flags(_state(positions, cash=5000.0, equity=50000.0), [_fills("US.NVDA", 3)], 100000.0)
    book = book_summary(_state(positions, cash=5000.0, equity=50000.0), flags, [_fills("US.NVDA", 3)])

    prompt = build_book_prompt(book)

    assert "must NOT tell the trader to buy or sell" in prompt
    assert "price target" in prompt
    assert "US.NVDA" in prompt
    assert "CONCENTRATION" in prompt
    assert "Not financial advice" in prompt


def test_without_a_provider_the_review_says_so(monkeypatch):
    settings = Settings(app_secret="t", deepseek_api_key=None, flowise_chatflow_id="")

    result = analyse_book({"positions": [], "flags": []}, settings)

    assert result.available is False
    assert "DEEPSEEK_API_KEY" in (result.reason or "")


def test_a_model_that_invents_a_figure_is_flagged(monkeypatch):
    from app.ai import analysis as ai

    monkeypatch.setattr(ai, "_call_flowise",
                        lambda p, s: ("Your book is worth $999,999.00 now.", "fake"))
    ai._cache.clear()
    settings = Settings(app_secret="t", deepseek_api_key=None, flowise_chatflow_id="cf")

    result = analyse_book(
        {"cash": 1000.0, "equity": 5000.0, "positions": [], "flags": []}, settings
    )

    assert result.unknown_figures, "an invented total must be reported"
    assert any("999,999" in f for f in result.unknown_figures)


# ------------------------------------------------------------------- the route


def _client(chatflow: str = "") -> TestClient:
    broker = FakeBroker()
    app = create_app(
        settings=Settings(
            app_secret="test-only",
            environment="development",
            deepseek_api_key=None,
            flowise_chatflow_id=chatflow,
        ),
        broker=broker,
        market=MarketCache(broker),
    )
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def test_the_route_returns_flags_even_with_no_model():
    body = _client().post("/api/paper/analysis").json()

    assert "flags" in body
    assert "account" in body
    assert body["available"] is False
    assert "DEEPSEEK_API_KEY" in body["reason"]


def test_the_route_is_post_only():
    assert _client().get("/api/paper/analysis").status_code == 405
