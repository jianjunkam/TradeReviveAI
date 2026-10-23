"""The Yahoo data source: parsing, symbol handling, and the failures it must not hide.

No network here. Every response is a fixture, so the suite stays fast and does not depend on
somebody else's servers staying up.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from app.broker.base import BrokerUnavailable
from app.broker.yahoo import YahooBroker, _market_row_from_quote, _quote_from_row

QUOTE_ROW = {
    "symbol": "AAPL",
    "shortName": "Apple Inc.",
    "regularMarketPrice": 348.22,
    "previousClose": 343.99,
    "regularMarketChangePercent": 1.2297,
    "regularMarketVolume": 46845411,
    "marketCap": 5081985449984,
    "trailingPE": 31.4,
    "bid": 348.2,
    "ask": 348.25,
    "regularMarketTime": 1792699201,
    "exchange": "NMS",
}


def test_a_quote_row_becomes_a_quote():
    quote = _quote_from_row(QUOTE_ROW)

    assert quote.symbol == "US.AAPL"
    assert quote.name == "Apple Inc."
    assert quote.last_price == 348.22
    assert quote.previous_close == 343.99
    assert quote.change_rate == 1.2297
    assert quote.source == "Yahoo Finance"


def test_a_missing_change_percent_is_derived_not_zeroed():
    row = dict(QUOTE_ROW)
    row.pop("regularMarketChangePercent")

    quote = _quote_from_row(row)

    assert quote.change_rate == pytest.approx((348.22 - 343.99) / 343.99 * 100, abs=1e-3)


def test_a_row_without_a_price_is_skipped_rather_than_faked():
    row = dict(QUOTE_ROW)
    row.pop("regularMarketPrice")

    assert _quote_from_row(row) is None


def test_a_row_without_a_previous_close_still_shows_a_price_but_no_change():
    row = dict(QUOTE_ROW)
    row.pop("previousClose")
    row.pop("regularMarketChangePercent")

    # A price without a baseline is still a price; the change is what must be absent.
    assert _quote_from_row(row) is None, "without a baseline the quote is unusable"
    market_row = _market_row_from_quote(row)
    assert market_row.last_price == 348.22
    assert market_row.change_rate is None


def test_the_market_row_carries_market_cap():
    row = _market_row_from_quote(QUOTE_ROW)

    assert row.symbol == "US.AAPL"
    assert row.market_cap == 5081985449984
    assert row.pe_ratio == 31.4


def test_symbols_are_normalised_and_validated():
    broker = YahooBroker(timeout=5)

    assert broker._bare("US.AAPL") == "AAPL"
    assert broker._bare("aapl") == "AAPL"
    assert broker._bare("BRK-B") == "BRK-B"
    with pytest.raises(BrokerUnavailable):
        broker._bare("MY.5225")


def test_an_empty_answer_is_an_error_with_a_reason(monkeypatch):
    broker = YahooBroker(timeout=5)
    monkeypatch.setattr(broker, "_crumb_token", lambda force=False: "crumb")

    def no_result(url, data=None, headers=None):
        return {"quoteResponse": {"result": None, "error": {"description": "No data found"}}}

    monkeypatch.setattr(broker, "_fetch", no_result)

    with pytest.raises(BrokerUnavailable) as caught:
        broker.quote("US.NOPE")
    assert "No data found" in str(caught.value)


def test_an_expired_token_is_refreshed_once_and_retried(monkeypatch):
    broker = YahooBroker(timeout=5)
    calls = {"crumb": 0, "fetch": 0}

    def crumb(force=False):
        calls["crumb"] += 1
        return f"crumb-{calls['crumb']}"

    def fetch(url, data=None, headers=None):
        calls["fetch"] += 1
        if calls["fetch"] == 1:
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)
        return {"quoteResponse": {"result": [QUOTE_ROW]}}

    monkeypatch.setattr(broker, "_crumb_token", crumb)
    monkeypatch.setattr(broker, "_fetch", fetch)

    quote = broker.quote("US.AAPL")

    assert quote.last_price == 348.22
    assert calls["crumb"] == 2, "the token must be re-issued, not reused"
    assert calls["fetch"] == 2


def test_a_network_failure_says_so(monkeypatch):
    broker = YahooBroker(timeout=5)
    monkeypatch.setattr(broker, "_crumb_token", lambda force=False: "crumb")

    def boom(url, data=None, headers=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(broker, "_fetch", boom)

    with pytest.raises(BrokerUnavailable) as caught:
        broker.quote("US.AAPL")
    assert "Could not reach Yahoo Finance" in str(caught.value)


def test_yahoo_has_no_positions_to_offer():
    with pytest.raises(BrokerUnavailable) as caught:
        YahooBroker(timeout=5).positions()
    assert "no brokerage account" in str(caught.value).lower()


def test_the_screener_defines_the_universe(monkeypatch):
    broker = YahooBroker(timeout=5, universe_size=3)
    payload = {
        "finance": {
            "result": [
                {
                    "total": 4560,
                    "quotes": [
                        {"symbol": "NVDA", "shortName": "NVIDIA Corporation", "exchange": "NMS"},
                        {"symbol": "JPM", "shortName": "JPMorgan Chase & Co.", "exchange": "NYQ"},
                        {"symbol": "SPY", "shortName": "SPDR S&P 500", "exchange": "PCX"},
                    ],
                }
            ]
        }
    }
    monkeypatch.setattr(broker, "_crumb_token", lambda force=False: "crumb")
    monkeypatch.setattr(broker, "_fetch", lambda url, data=None, headers=None: payload)

    universe = broker.universe()

    assert [s.symbol for s in universe] == ["US.NVDA", "US.JPM", "US.SPY"]
    assert universe[0].exchange == "US_NASDAQ"
    assert universe[1].exchange == "US_NYSE"
    assert universe[2].exchange == "US_AMEX"


def test_the_screener_query_asks_for_market_cap_order(monkeypatch):
    broker = YahooBroker(timeout=5, universe_size=100)
    captured = {}

    def fetch(url, data=None, headers=None):
        captured["body"] = json.loads(data.decode())
        return {"finance": {"result": [{"quotes": [{"symbol": "AAPL", "exchange": "NMS"}]}]}}

    monkeypatch.setattr(broker, "_crumb_token", lambda force=False: "crumb")
    monkeypatch.setattr(broker, "_fetch", fetch)
    broker.universe()

    assert captured["body"]["sortField"] == "intradaymarketcap"
    assert captured["body"]["sortType"] == "DESC"
    assert captured["body"]["size"] == 100
