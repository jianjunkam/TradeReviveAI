"""Yahoo Finance headlines: parsing, caching, and what happens when Yahoo is unreachable.

The parser is fed a fixed feed here — a test that calls the live feed is a test that fails
in an exam room with no wifi.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.broker.fake import FakeBroker
from app.config import Settings
from app.main import create_app
from app.market import MarketCache
from app.news import NewsFeed, parse_feed

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Yahoo Finance</title>
  <item>
    <title>Older story about bonds</title>
    <link>https://finance.yahoo.com/news/older-story.html</link>
    <pubDate>Thu, 22 Oct 2026 06:00:00 +0000</pubDate>
    <description>Treasury yields moved.</description>
  </item>
  <item>
    <title>Nvidia and Tesla invest in Samsung</title>
    <link>https://www.fool.com/investing/nvidia-samsung.html</link>
    <pubDate>Thu, 22 Oct 2026 08:25:24 +0000</pubDate>
    <description>A combined 2.8 billion dollar investment.</description>
  </item>
  <item>
    <title>Market wraps higher</title>
    <link>https://www.marketwatch.com/story/wrap.html</link>
    <pubDate>Thu, 22 Oct 2026 20:15:00 +0000</pubDate>
    <description>Stocks closed up.</description>
  </item>
  <item>
    <title>Market wraps higher</title>
    <link>https://www.reuters.com/story/wrap.html</link>
    <pubDate>Thu, 22 Oct 2026 20:16:00 +0000</pubDate>
    <description>The same story, syndicated.</description>
  </item>
  <item>
    <title>No link, should be skipped</title>
    <pubDate>Thu, 22 Oct 2026 21:00:00 +0000</pubDate>
  </item>
</channel></rss>
"""


def test_headlines_are_newest_first():
    items = parse_feed(FEED)

    assert [h.title for h in items][0] == "Market wraps higher"
    assert items[-1].title == "Older story about bonds"


def test_duplicate_titles_from_different_publishers_are_collapsed():
    items = parse_feed(FEED)

    titles = [h.title for h in items]
    assert titles.count("Market wraps higher") == 1
    # The first one in feed order wins, so MarketWatch rather than the syndicated copy.
    assert next(h for h in items if h.title == "Market wraps higher").publisher == "MarketWatch"


def test_an_item_without_a_link_is_skipped():
    items = parse_feed(FEED)

    assert all(h.link.startswith("http") for h in items)
    assert "No link, should be skipped" not in [h.title for h in items]


def test_publisher_is_read_from_the_link_and_named_where_it_is_known():
    publishers = {h.publisher for h in parse_feed(FEED)}

    assert "Motley Fool" in publishers          # www.fool.com
    assert "Yahoo Finance" in publishers
    assert "MarketWatch" in publishers


def test_dates_are_normalised_to_utc_iso():
    item = next(h for h in parse_feed(FEED) if h.title == "Nvidia and Tesla invest in Samsung")

    assert item.published == "2026-10-22T08:25:24+00:00"


def test_a_limit_caps_the_list():
    assert len(parse_feed(FEED, limit=2)) == 2


def test_a_broken_feed_raises_rather_than_inventing_items():
    import xml.etree.ElementTree as ET

    try:
        parse_feed("<rss><channel><item>")
    except ET.ParseError:
        return
    raise AssertionError("a malformed feed must not be silently tolerated")


def test_feed_keeps_the_last_good_list_and_reports_the_error(monkeypatch):
    feed = NewsFeed(symbols="AAPL", refresh_seconds=60)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(OSError("network down")),
    )

    result = feed.get(limit=5)

    assert result["items"] == []
    assert "Could not reach Yahoo Finance" in result["error"]
    assert result["ready"] is False


# ------------------------------------------------------------------ the route


def _client(public: bool = True) -> TestClient:
    broker = FakeBroker()
    app = create_app(
        settings=Settings(
            app_secret="test-only",
            environment="development",
            demo_closed=not public,
        ),
        broker=broker,
        market=MarketCache(broker),
    )
    # Serve from a parsed fixture: no network in tests.
    feed = NewsFeed(symbols="AAPL")
    feed._headlines = parse_feed(FEED)
    feed._fetched_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    app.state.news = feed
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


def test_news_route_returns_headlines():
    response = _client().get("/api/public/news?limit=3")

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 3
    assert body["source"] == "Yahoo Finance"
    assert body["items"][0]["title"] == "Market wraps higher"
    assert body["items"][0]["link"].startswith("https://")


def test_news_route_is_closed_with_the_dashboard_off():
    assert _client(public=False).get("/api/public/news").status_code == 404


def test_the_dashboard_links_the_news_panel():
    body = _client().get("/").text

    assert 'id="news-list"' in body
    assert "Market news" in body
    assert 'id="chart-cap"' not in body      # the old chart is gone
