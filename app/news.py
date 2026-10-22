"""Market headlines from Yahoo Finance.

Yahoo has no official news API. Two routes exist: the search JSON endpoint and the RSS
headline feed. RSS is the stable one — no key, no cookie, no crumb — so that is what this
uses, with the publisher derived from the link because the feed does not always name it.

Fetched on the server, not in the browser: Yahoo sends no CORS headers, so a direct
`fetch()` from the page would fail. The result is cached, because headlines do not change
faster than a few minutes and the feed is somebody else's server.
"""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

REQUEST_TIMEOUT = 10.0
USER_AGENT = "Mozilla/5.0 (compatible; TradeReviveAI/1.0)"

#: Nicer names for the domains that show up most in the feed.
PUBLISHERS = {
    "finance.yahoo.com": "Yahoo Finance",
    "www.fool.com": "Motley Fool",
    "fool.com": "Motley Fool",
    "www.barrons.com": "Barron's",
    "www.marketwatch.com": "MarketWatch",
    "www.reuters.com": "Reuters",
    "www.bloomberg.com": "Bloomberg",
    "www.benzinga.com": "Benzinga",
    "www.investors.com": "Investor's Business Daily",
    "www.cnbc.com": "CNBC",
    "www.zacks.com": "Zacks",
    "www.investopedia.com": "Investopedia",
}


@dataclass
class Headline:
    title: str
    link: str
    publisher: str
    published: str | None      # ISO 8601, UTC
    summary: str

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "link": self.link,
            "publisher": self.publisher,
            "published": self.published,
            "summary": self.summary,
        }


def _publisher_for(link: str) -> str:
    try:
        host = urllib.parse.urlsplit(link).netloc.lower()
    except ValueError:
        return "Yahoo Finance"
    if not host:
        return "Yahoo Finance"
    if host in PUBLISHERS:
        return PUBLISHERS[host]
    return host.removeprefix("www.").split(".")[0].replace("-", " ").title()


def _text(element, tag: str) -> str:
    found = element.find(tag)
    return (found.text or "").strip() if found is not None else ""


def parse_feed(xml_text: str, limit: int = 12) -> list[Headline]:
    """RSS in, headlines out. A malformed item is skipped, never guessed at."""
    root = ET.fromstring(xml_text)
    headlines: list[Headline] = []
    seen: set[str] = set()

    for item in root.findall("./channel/item"):
        title = _text(item, "title")
        link = _text(item, "link")
        if not title or not link:
            continue
        key = title.strip().lower()
        if key in seen:                      # one story, several tickers
            continue
        seen.add(key)

        published = None
        raw_date = _text(item, "pubDate")
        if raw_date:
            try:
                published = (
                    parsedate_to_datetime(raw_date)
                    .astimezone(timezone.utc)
                    .isoformat(timespec="seconds")
                )
            except (TypeError, ValueError):
                published = None

        summary = _text(item, "description")
        if len(summary) > 240:
            summary = summary[:237].rstrip() + "…"

        headlines.append(
            Headline(
                title=title,
                link=link,
                publisher=_publisher_for(link),
                published=published,
                summary=summary,
            )
        )

    headlines.sort(key=lambda h: h.published or "", reverse=True)
    return headlines[:limit]


class NewsFeed:
    """Cached Yahoo Finance headlines for a set of tickers."""

    TEMPLATE = (
        "https://feeds.finance.yahoo.com/rss/2.0/headline"
        "?s={symbols}&region=US&lang=en-US"
    )

    def __init__(self, symbols: str = "AAPL,MSFT,NVDA,AMZN,TSLA", refresh_seconds: int = 600):
        self.symbols = ",".join(s.strip() for s in symbols.split(",") if s.strip())
        self._refresh_seconds = max(60, int(refresh_seconds))
        self._lock = threading.Lock()
        self._headlines: list[Headline] = []
        self._fetched_at: datetime | None = None
        self._error: str | None = None

    # ------------------------------------------------------------------ fetch

    def refresh(self) -> None:
        url = self.TEMPLATE.format(symbols=self.symbols or "AAPL")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                payload = response.read().decode("utf-8", errors="replace")
            headlines = parse_feed(payload, limit=40)
            if not headlines:
                raise ValueError("the feed returned no headlines")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, ET.ParseError) as exc:
            with self._lock:
                # Keep the last good list: stale headlines beat an empty panel, and the
                # age is reported so the page can say how old they are.
                self._error = f"Could not reach Yahoo Finance: {exc}"
            return

        with self._lock:
            self._headlines = headlines
            self._fetched_at = datetime.now(timezone.utc)
            self._error = None

    # ------------------------------------------------------------------- read

    def get(self, limit: int = 8) -> dict:
        stale = (
            self._fetched_at is None
            or (datetime.now(timezone.utc) - self._fetched_at).total_seconds()
            > self._refresh_seconds
        )
        if stale:
            self.refresh()

        with self._lock:
            age = (
                round((datetime.now(timezone.utc) - self._fetched_at).total_seconds(), 1)
                if self._fetched_at
                else None
            )
            return {
                "items": [h.as_dict() for h in self._headlines[: max(1, min(limit, 30))]],
                "symbols": self.symbols.split(","),
                "source": "Yahoo Finance",
                "fetched_at": self._fetched_at.isoformat() if self._fetched_at else None,
                "age_seconds": age,
                "error": self._error,
                "ready": bool(self._headlines),
            }
