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


# ---------------------------------------------------------------- news context

HEADLINES = [
    {"symbol": "NVDA", "title": "Nvidia beats estimates as data-centre sales surge",
     "publisher": "Reuters", "published": "2026-10-22T20:00:00+00:00",
     "link": "https://example.test/1", "summary": ""},
    {"symbol": "KO", "title": "Coca-Cola raises full-year outlook",
     "publisher": "Yahoo Finance", "published": "2026-10-21T13:00:00+00:00",
     "link": "https://example.test/2", "summary": ""},
]


def test_the_prompt_carries_headlines_with_their_symbols():
    prompt = ai.build_prompt(SUMMARY, HEADLINES)

    assert "NVDA: Nvidia beats estimates" in prompt
    assert "KO: Coca-Cola raises" in prompt
    assert "unverified" in prompt.lower()


def test_without_headlines_the_model_is_told_to_ignore_news():
    prompt = ai.build_prompt(SUMMARY, [])

    assert "No headlines were available" in prompt
    assert "do not guess at what the news might say" in prompt.lower()


def test_a_headline_figure_is_not_flagged_as_invented():
    """If a headline says '$4 billion', the model may repeat it."""
    headlines = [{"symbol": "NVDA", "title": "Nvidia adds $4 billion to buybacks"}]

    assert ai.unknown_figures("Nvidia added $4 billion to buybacks.", SUMMARY, headlines) == []
    # Outside a headline the same words are a figure nobody supplied.
    assert ai.unknown_figures("Nvidia added $4 billion to buybacks.", SUMMARY, []) == ["$4"]


def test_the_route_sends_the_held_symbols_to_the_news_feed(monkeypatch):
    captured = {}

    class FakeNews:
        def for_symbols(self, symbols, limit=8, per_symbol=3):
            captured["symbols"] = symbols
            return {"items": HEADLINES, "symbols": symbols, "error": None, "ready": True}

    def capture(prompt, settings):
        captured["prompt"] = prompt
        return "review", "fake-model"

    monkeypatch.setattr(ai, "_call_flowise", capture)
    ai._cache.clear()

    client = _client(chatflow="test-chatflow")
    client.app.state.news = FakeNews()
    body = client.post("/api/journal/analysis").json()

    assert body["available"] is True
    assert body["headlines"] == HEADLINES
    assert "Nvidia beats estimates" in captured["prompt"]
    # US. prefix stripped, because Yahoo wants NVDA not US.NVDA
    assert all(not s.startswith("US.") for s in captured["symbols"])


def test_the_headline_list_is_capped():
    class Many:
        def for_symbols(self, symbols, limit=8, per_symbol=3):
            return {"items": [dict(HEADLINES[0], title=f"story {n}") for n in range(50)],
                    "symbols": symbols, "error": None, "ready": True}

    assert len(Many().for_symbols(["AAPL"])["items"]) == 50  # the fake itself is not capped
    # the prompt, however, only ever shows eight
    prompt = ai.build_prompt(SUMMARY, [dict(HEADLINES[0], title=f"story {n}") for n in range(50)])
    assert "story 7" in prompt and "story 8" not in prompt


def test_the_prompt_admits_when_positions_are_not_marked_to_market():
    """Net P&L equals realised P&L when no live price was available: say so, do not hide it."""
    at_cost = dict(SUMMARY, marks_at_cost=True, unrealised=0.0)

    told = ai.build_prompt(at_cost, [])
    not_told = ai.build_prompt(dict(SUMMARY, marks_at_cost=False), [])

    assert "valued at cost" in told
    assert "net P&L equals realised P&L" in told
    assert "valued at cost" not in not_told


def test_the_summary_says_when_it_has_no_live_prices():
    body = _client().get("/api/journal/summary").json()

    assert "marks_at_cost" in body
    assert isinstance(body["marks_at_cost"], bool)
    # A cold market cache cannot price anything, so open positions must be flagged.
    if body["open_positions"]:
        assert body["marks_at_cost"] is True
