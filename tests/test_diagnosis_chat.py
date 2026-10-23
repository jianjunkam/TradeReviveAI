"""The diagnosis chat: the proxy must pass the question through and report failures honestly.

No network: the Flowise call is stubbed. What is pinned here is the contract the page relies
on — a text answer, a session id that survives a reload, and an error the reader can read
instead of a silent spinner.
"""

from __future__ import annotations

import json
import urllib.error

import pytest
from fastapi.testclient import TestClient

from app.broker.fake import FakeBroker
from app.config import Settings
from app.main import create_app
from app.market import MarketCache
from app.routes import diagnosis as diagnosis_route


def _client(chatflow: str = "test-chatflow", host: str = "flowise.test") -> TestClient:
    broker = FakeBroker()
    app = create_app(
        settings=Settings(
            app_secret="test-only",
            environment="development",
            flowise_host=host,
            flowise_chatflow_id=chatflow,
        ),
        broker=broker,
        market=MarketCache(broker),
    )
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def test_a_question_comes_back_as_an_answer(monkeypatch):
    captured = {}

    class FakeResponse:
        def read(self):
            return json.dumps({"text": "Drawdown is the distance from your peak."}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode())
        return FakeResponse()

    monkeypatch.setattr(diagnosis_route.urllib.request, "urlopen", fake_urlopen)

    body = _client().post(
        "/api/diagnosis/chat",
        json={"message": "What is drawdown?", "session_id": "diag-abc"},
    ).json()

    assert body["text"].startswith("Drawdown is")
    assert "test-chatflow" in captured["url"]
    assert captured["body"]["question"] == "What is drawdown?"
    assert captured["body"]["overrideConfig"]["sessionId"] == "diag-abc"


def test_an_empty_question_is_refused(monkeypatch):
    response = _client().post("/api/diagnosis/chat", json={"message": "   "})

    assert response.status_code == 422


def test_an_over_long_question_is_refused():
    response = _client().post("/api/diagnosis/chat", json={"message": "x" * 3000})

    assert response.status_code == 422


def test_an_unreachable_assistant_says_so(monkeypatch):
    def boom(request, timeout=0):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(diagnosis_route.urllib.request, "urlopen", boom)

    response = _client().post("/api/diagnosis/chat", json={"message": "hello"})

    assert response.status_code == 503
    assert "could not be reached" in response.json()["detail"].lower()


def test_an_empty_answer_is_an_error_not_a_blank_bubble(monkeypatch):
    class Blank:
        def read(self):
            return json.dumps({"text": ""}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(diagnosis_route.urllib.request, "urlopen", lambda r, timeout=0: Blank())

    response = _client().post("/api/diagnosis/chat", json={"message": "hello"})

    assert response.status_code == 502
    assert "empty" in response.json()["detail"].lower()


def test_no_chatflow_configured_is_a_503_with_instructions():
    response = _client(chatflow="").post("/api/diagnosis/chat", json={"message": "hello"})

    assert response.status_code == 503
    assert "FLOWISE_CHATFLOW_ID" in response.json()["detail"]


def test_the_page_has_no_dead_controls():
    """The old page shipped buttons that did nothing; the transcript is the page now."""
    page = _client().get("/diagnosis").text

    assert "Open the chat" not in page
    assert "prompt-grid" not in page
    assert 'id="chat-log"' in page
    assert 'id="chat-form"' in page
    assert "flowise-embed" not in page


def test_the_rate_limit_stops_a_runaway_tab(monkeypatch):
    class OK:
        def read(self):
            return json.dumps({"text": "fine"}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(diagnosis_route.urllib.request, "urlopen", lambda r, timeout=0: OK())
    diagnosis_route._recent.clear()

    client = _client()
    codes = [client.post("/api/diagnosis/chat", json={"message": f"q{n}"}).status_code
             for n in range(diagnosis_route.RATE_LIMIT + 2)]

    assert codes[0] == 200
    assert codes[-1] == 429
    diagnosis_route._recent.clear()
