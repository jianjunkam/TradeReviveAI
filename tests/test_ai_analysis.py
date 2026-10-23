"""The AI section: what the model is allowed to see, and what happens when it is missing.

The tests never call a provider. They pin the contract instead: the prompt carries only the
journal's own figures and the prohibitions, an unconfigured install says so, and two identical
calls cost one request.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.ai import analysis as ai
from app.broker.fake import FakeBroker
from app.config import Settings
from app.main import create_app
from app.market import MarketCache

SUMMARY = {
    "closed_trades": 56,
    "win_rate": 62.5,
    "profit_factor": 2.35,
    "avg_win": 145.26,
    "avg_loss": 103.21,
    "best": 500.88,
    "worst": -314.40,
    "net_pl": 3509.97,
    "realised": 2916.48,
    "unrealised": 593.49,
    "equity": 102916.48,
    "starting_cash": 100000.0,
    "max_drawdown": 826.47,
    "max_drawdown_pct": 0.8,
    "mistakes": [
        {"rule": "OVERTRADING", "label": "Three or more exits in a day", "count": 13, "cost": 1028.13},
        {"rule": "QUICK_LOSS_EXIT", "label": "Cut within two days", "count": 6, "cost": 646.57},
    ],
}


def test_the_prompt_carries_the_numbers_and_nothing_else():
    prompt = ai.build_prompt(SUMMARY)

    for value in ("56", "62.5", "2.35", "145.26", "103.21", "$3,509.97", "$1,028.13"):
        assert value in prompt, value


def test_the_prompt_forbids_signals_and_predictions():
    prompt = ai.build_prompt(SUMMARY).lower()

    assert "never recommend buying or selling" in prompt
    assert "never predict prices" in prompt
    assert "not financial advice" in prompt


def test_no_provider_means_an_honest_refusal():
    settings = Settings(app_secret="t", deepseek_api_key=None, flowise_chatflow_id="")

    result = ai.analyse(SUMMARY, settings)

    assert result.available is False
    assert "DEEPSEEK_API_KEY" in (result.reason or "")
    assert result.text is None


def test_one_model_call_serves_repeated_requests(monkeypatch):
    calls = {"n": 0}

    def fake(prompt, settings):
        calls["n"] += 1
        return "a review", "fake-model"

    monkeypatch.setattr(ai, "_call_flowise", fake)
    settings = Settings(app_secret="t", deepseek_api_key=None,
                        flowise_chatflow_id="test-chatflow")
    ai._cache.clear()

    first = ai.analyse(SUMMARY, settings)
    second = ai.analyse(SUMMARY, settings)

    assert first.available and second.available
    assert calls["n"] == 1, "the second request must come from the cache"
    assert second.cached is True


def test_a_provider_failure_does_not_become_a_fake_review(monkeypatch):
    def boom(prompt, settings):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(ai, "_call_flowise", boom)
    settings = Settings(app_secret="t", deepseek_api_key=None,
                        flowise_chatflow_id="test-chatflow")
    ai._cache.clear()

    result = ai.analyse(SUMMARY, settings)

    assert result.available is False
    assert "connection refused" in (result.reason or "")
    assert result.text is None


# ------------------------------------------------------------------ the route


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


def test_the_route_says_when_no_model_is_configured():
    response = _client().post("/api/journal/analysis")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert "DEEPSEEK_API_KEY" in body["reason"]


def test_the_route_returns_the_model_text_when_configured(monkeypatch):
    monkeypatch.setattr(ai, "_call_flowise", lambda p, s: ("coach text", "flowise chatflow"))
    ai._cache.clear()

    body = _client(chatflow="test-chatflow").post("/api/journal/analysis").json()

    assert body["available"] is True
    assert body["text"] == "coach text"
    assert body["provider"] == "flowise"


def test_the_analysis_is_post_only():
    """It spends money: a page refresh must not trigger it."""
    assert _client().get("/api/journal/analysis").status_code == 405


def test_figures_the_model_invented_are_flagged():
    """The model once added net P&L to equity and reported a total nobody supplied."""
    text = "Equity is $103,509.97 with net P&L of $3,509.97 and drawdown of $826.47."

    strays = ai.unknown_figures(text, SUMMARY)

    assert "$103,509.97" in strays
    assert "$3,509.97" not in strays        # this one was supplied
    assert "$826.47" not in strays


def test_a_clean_reply_has_no_flags(monkeypatch):
    monkeypatch.setattr(
        ai, "_call_flowise",
        lambda p, s: ("Net P&L was $3,509.97 and max drawdown $826.47.", "flowise chatflow"),
    )
    ai._cache.clear()
    settings = Settings(app_secret="t", deepseek_api_key=None, flowise_chatflow_id="cf")

    result = ai.analyse(SUMMARY, settings)

    assert result.unknown_figures == []
