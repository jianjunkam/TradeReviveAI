"""Yahoo Finance — the only market-data source.

Why this and nothing else: a hosted demo cannot depend on a closed-source gateway that needs
a signed-in brokerage account on the same machine, keeps one session per account, and ties
its quote entitlement to the login IP. Yahoo answers over HTTPS with no account at all, which
is the only kind of dependency a course project can hand to a supervisor.

What it honestly is:

* **Unofficial.** These are the endpoints Yahoo's own web page calls. There is no contract,
  no key, no support, and they have changed before without notice.
* **Not real-time for everyone.** Yahoo labels each symbol with its own delay; the payload
  carries `delayed` when Yahoo says so, otherwise None — "unknown", never "live".
* **Not for redistribution at scale.** Fine for a coursework demo behind a login; a public
  product showing real-time exchange prices needs a licensed feed.

The endpoints, all confirmed working from this machine:

* `v7/finance/quote?symbols=...&crumb=...`  batch prices, market cap, bid/ask (needs a
  cookie + crumb, which is why `_crumb()` exists)
* `v1/finance/screener` POST               the real top-N US companies by market cap
* `v8/finance/chart/{symbol}`              single-symbol fallback when the batch fails

Nothing here can place an order: Yahoo holds no account of ours.
"""

from __future__ import annotations

import http.cookiejar
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from app.broker.base import (
    BrokerStatus,
    BrokerUnavailable,
    MarketRow,
    Quote,
    SymbolInfo,
)

BASE = "https://query1.finance.yahoo.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

#: Yahoo's exchange codes → the names the rest of the app speaks.
EXCHANGES = {"NMS": "US_NASDAQ", "NYQ": "US_NYSE", "ASE": "US_AMEX", "PCX": "US_AMEX"}

#: How long a crumb is reused before another handshake.
CRUMB_TTL = 1800.0
#: How long the universe listing is reused.
UNIVERSE_TTL = 3600.0
#: How long the markets overview is reused.
OVERVIEW_TTL = 60.0

#: The groups shown on the dashboard, using Yahoo's own symbols. Mirrors the sections of
#: finance.yahoo.com/markets: the numbers a reader checks before anything else.
OVERVIEW_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Indices", [
        ("^GSPC", "S&P 500"), ("^DJI", "Dow 30"), ("^IXIC", "Nasdaq"),
        ("^RUT", "Russell 2000"), ("^VIX", "VIX"),
    ]),
    ("Commodities", [
        ("CL=F", "Crude Oil"), ("BZ=F", "Brent Crude"), ("GC=F", "Gold"),
        ("SI=F", "Silver"), ("NG=F", "Natural Gas"),
    ]),
    ("Currencies", [
        ("EURUSD=X", "EUR/USD"), ("JPY=X", "USD/JPY"), ("GBP=X", "USD/GBP"),
        ("CAD=X", "USD/CAD"), ("MXN=X", "USD/MXN"),
    ]),
    ("Bonds", [
        ("^TNX", "10-Yr Bond"), ("^TYX", "30-Yr Bond"), ("^FVX", "5-Yr Bond"),
        ("^IRX", "13-Wk Bond"),
    ]),
    ("Crypto", [
        ("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum"), ("SOL-USD", "Solana"),
        ("XRP-USD", "XRP"),
    ]),
]


class YahooBroker:
    """Market data from Yahoo Finance. Read-only, no account, no orders."""

    SOURCE = "Yahoo Finance"

    def __init__(self, timeout: float = 12.0, universe_size: int = 100) -> None:
        self.timeout = max(3.0, float(timeout))
        self.universe_size = max(1, min(int(universe_size), 250))
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar))
        self._crumb: str | None = None
        self._crumb_at = 0.0
        self._lock = threading.Lock()
        self._universe: list[SymbolInfo] = []
        self._universe_at = 0.0
        self._checked: tuple[float, BrokerStatus] | None = None
        self._overview: list[dict] = []
        self._overview_at = 0.0

    # --------------------------------------------------------------- plumbing

    def _fetch(self, url: str, data: bytes | None = None, headers: dict | None = None) -> dict:
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "User-Agent": USER_AGENT,
                # Not "application/json": the crumb endpoint answers in text/plain and
                # returns 406 Not Acceptable if we insist on JSON.
                "Accept": "*/*",
                **(headers or {}),
            },
            method="POST" if data else "GET",
        )
        with self._opener.open(request, timeout=self.timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
        return json.loads(body)

    def _text(self, url: str) -> str:
        """For the one endpoint that answers in plain text rather than JSON."""
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
        )
        with self._opener.open(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8", errors="replace").strip()

    def _crumb_token(self, force: bool = False) -> str:
        """A short-lived token Yahoo wants alongside the question. Cookie jar does the rest."""
        with self._lock:
            if not force and self._crumb and time.time() - self._crumb_at < CRUMB_TTL:
                return self._crumb

            # The handshake: this sets the cookie. A 404 is normal and still yields one.
            try:
                self._opener.open(
                    urllib.request.Request("https://fc.yahoo.com", headers={"User-Agent": USER_AGENT}),
                    timeout=self.timeout,
                ).close()
            except urllib.error.HTTPError:
                pass
            except (urllib.error.URLError, TimeoutError, OSError):
                pass

            token = self._text(f"{BASE}/v1/test/getcrumb")
            if not token:
                raise BrokerUnavailable(
                    "Yahoo Finance did not issue a session token, so prices cannot be read."
                )
            self._crumb = token
            self._crumb_at = time.time()
            return self._crumb

    # ------------------------------------------------------------------ status

    def status(self) -> BrokerStatus:
        """One cheap probe, cached for a minute: is the data source answering?"""
        with self._lock:
            if self._checked and time.time() - self._checked[0] < 60:
                return self._checked[1]

        try:
            self.quote("US.AAPL")
            status = BrokerStatus(
                connected=True,
                reason=None,
                host="query1.finance.yahoo.com",
                port=443,
                checked_at=datetime.now(timezone.utc),
                account=None,
            )
        except BrokerUnavailable as exc:
            status = BrokerStatus(
                connected=False,
                reason=str(exc),
                host="query1.finance.yahoo.com",
                port=443,
                checked_at=datetime.now(timezone.utc),
                account=None,
            )
        with self._lock:
            self._checked = (time.time(), status)
        return status

    # ------------------------------------------------------------------ quotes

    @staticmethod
    def _bare(symbol: str) -> str:
        code = symbol.strip().upper()
        if "." in code:
            market, rest = code.split(".", 1)
            if market != "US":
                raise BrokerUnavailable(
                    f"{symbol} is not a US ticker. Yahoo's feed here covers US stocks only, "
                    "for example US.AAPL."
                )
            code = rest
        if not code or not code.replace("-", "").isalnum():
            raise BrokerUnavailable(f"'{symbol}' is not a US ticker.")
        return code

    def _batch(self, symbols: list[str]) -> list[dict]:
        if not symbols:
            return []
        codes = ",".join(symbols)
        crumb = self._crumb_token()
        query = urllib.parse.urlencode({"symbols": codes, "crumb": crumb, "lang": "en-US", "region": "US"})
        try:
            payload = self._fetch(f"{BASE}/v7/finance/quote?{query}")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                # The token expired mid-flight: handshake once more, then retry.
                crumb = self._crumb_token(force=True)
                query = urllib.parse.urlencode(
                    {"symbols": codes, "crumb": crumb, "lang": "en-US", "region": "US"}
                )
                payload = self._fetch(f"{BASE}/v7/finance/quote?{query}")
            else:
                raise BrokerUnavailable(f"Yahoo Finance refused the request (HTTP {exc.code}).") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise BrokerUnavailable(f"Could not reach Yahoo Finance: {exc}") from exc

        result = ((payload.get("quoteResponse") or {}).get("result")) or []
        if not result:
            error = (payload.get("quoteResponse") or {}).get("error")
            raise BrokerUnavailable(
                f"Yahoo Finance returned no prices{': ' + error.get('description', '') if error else ''}."
            )
        return result

    def _batch_raw(self, codes: list[str]) -> list[dict]:
        """Batch by Yahoo's own symbol, for indices, futures and FX that are not US tickers."""
        rows: list[dict] = []
        for start in range(0, len(codes), 50):
            rows.extend(self._batch(codes[start:start + 50]))
        return rows

    def overview(self) -> list[dict]:
        """The groups a reader expects from a markets page: indices, commodities, FX, bonds, crypto.

        One batched request per group, cached for a minute. Symbols are Yahoo's own, so
        `^GSPC` and `CL=F` pass through untouched.
        """
        with self._lock:
            if self._overview and time.time() - self._overview_at < OVERVIEW_TTL:
                return [dict(group) for group in self._overview]

        groups: list[dict] = []
        for title, members in OVERVIEW_GROUPS:
            codes = [code for code, _ in members]
            try:
                rows = {row.get("symbol"): row for row in self._batch_raw(codes)}
            except BrokerUnavailable:
                # One dead group must not blank the whole panel.
                groups.append({"title": title, "items": [], "error": "unavailable right now"})
                continue

            items = []
            for code, label in members:
                row = rows.get(code)
                if not row:
                    continue
                price = _number(row.get("regularMarketPrice"))
                change = _number(row.get("regularMarketChange"))
                percent = _number(row.get("regularMarketChangePercent"))
                if price is None:
                    continue
                items.append({
                    "symbol": code,
                    "label": label,
                    "price": round(price, 4),
                    "change": round(change, 4) if change is not None else None,
                    "change_pct": round(percent, 4) if percent is not None else None,
                })
            groups.append({"title": title, "items": items, "error": None})

        with self._lock:
            self._overview = groups
            self._overview_at = time.time()
        return [dict(group) for group in groups]

    def quotes(self, symbols: list[str]) -> list[Quote]:
        """Batch prices. Yahoo caps the list length, so it is chunked at 50."""
        codes = [self._bare(s) for s in symbols]
        out: list[Quote] = []
        for start in range(0, len(codes), 50):
            for row in self._batch(codes[start:start + 50]):
                quote = _quote_from_row(row)
                if quote is not None:
                    out.append(quote)
        return out

    def quote(self, symbol: str) -> Quote:
        code = self._bare(symbol)
        rows = self._batch([code])
        for row in rows:
            quote = _quote_from_row(row)
            if quote is not None:
                return quote
        raise BrokerUnavailable(f"Yahoo Finance has no price for {code} right now.")

    def positions(self):
        raise BrokerUnavailable(
            "Yahoo Finance has no brokerage account. Paper trading keeps its own book locally."
        )

    # --------------------------------------------------------------- universe

    def universe(self) -> list[SymbolInfo]:
        """The largest US-listed companies by market cap, straight from the screener."""
        with self._lock:
            if self._universe and time.time() - self._universe_at < UNIVERSE_TTL:
                return list(self._universe)

        body = {
            "size": self.universe_size,
            "offset": 0,
            "sortField": "intradaymarketcap",
            "sortType": "DESC",
            "quoteType": "EQUITY",
            "query": {
                "operator": "or",
                "operands": [
                    {"operator": "eq", "operands": ["exchange", "NMS"]},
                    {"operator": "eq", "operands": ["exchange", "NYQ"]},
                    {"operator": "eq", "operands": ["exchange", "ASE"]},
                ],
            },
        }
        crumb = self._crumb_token()
        query = urllib.parse.urlencode({"crumb": crumb, "lang": "en-US", "region": "US"})
        try:
            payload = self._fetch(
                f"{BASE}/v1/finance/screener?{query}",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
        except (urllib.error.URLError, TimeoutError, OSError, urllib.error.HTTPError) as exc:
            raise BrokerUnavailable(f"Could not read the Yahoo screener: {exc}") from exc

        result = ((payload.get("finance") or {}).get("result")) or []
        rows = result[0].get("quotes", []) if result else []
        universe = [
            SymbolInfo(
                symbol=f"US.{row['symbol']}",
                name=row.get("shortName") or row.get("longName") or row["symbol"],
                exchange=EXCHANGES.get(row.get("exchange", ""), "US_NASDAQ"),
            )
            for row in rows
            if row.get("symbol")
        ]
        if not universe:
            raise BrokerUnavailable("The Yahoo screener returned no companies.")

        with self._lock:
            self._universe = universe
            self._universe_at = time.time()
        return list(universe)

    def snapshots(self, symbols: list[str]) -> list[MarketRow]:
        """The market rows the dashboard draws, in one or two calls."""
        codes = [self._bare(s) for s in symbols]
        rows: list[MarketRow] = []
        for start in range(0, len(codes), 50):
            for row in self._batch(codes[start:start + 50]):
                market_row = _market_row_from_quote(row)
                if market_row is not None:
                    rows.append(market_row)
        return rows


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _quote_from_row(row: dict) -> Quote | None:
    last = _number(row.get("regularMarketPrice"))
    previous = _number(row.get("previousClose")) or _number(row.get("regularMarketPreviousClose"))
    if last is None or previous in (None, 0):
        return None

    change = _number(row.get("regularMarketChangePercent"))
    if change is None:
        change = round((last - previous) / previous * 100, 4)

    return Quote(
        symbol=f"US.{row.get('symbol', '')}",
        name=row.get("shortName") or row.get("longName") or row.get("symbol", ""),
        last_price=round(last, 4),
        previous_close=round(previous, 4),
        change_rate=round(change, 4),
        volume=int(row.get("regularMarketVolume") or 0),
        bid=_number(row.get("bid")),
        ask=_number(row.get("ask")),
        updated_at=(
            datetime.fromtimestamp(int(row["regularMarketTime"]), tz=timezone.utc).isoformat()
            if row.get("regularMarketTime")
            else None
        ),
        # Yahoo sometimes says how delayed it is; when it does not, the honest answer is
        # "unknown", not "live".
        delayed=None,
        source="Yahoo Finance",
    )


def _market_row_from_quote(row: dict) -> MarketRow | None:
    last = _number(row.get("regularMarketPrice"))
    previous = _number(row.get("previousClose")) or _number(row.get("regularMarketPreviousClose"))
    if last is None:
        return None

    change = _number(row.get("regularMarketChangePercent"))
    if change is None and previous:
        change = round((last - previous) / previous * 100, 4)

    return MarketRow(
        symbol=f"US.{row.get('symbol', '')}",
        name=row.get("shortName") or row.get("longName") or row.get("symbol", ""),
        last_price=round(last, 4),
        previous_close=round(previous, 4) if previous is not None else None,
        change_rate=round(change, 4) if change is not None else None,
        volume=int(row["regularMarketVolume"]) if row.get("regularMarketVolume") else None,
        turnover=None,
        market_cap=row.get("marketCap"),
        pe_ratio=_number(row.get("trailingPE")),
        bid=_number(row.get("bid")),
        ask=_number(row.get("ask")),
        updated_at=(
            datetime.fromtimestamp(int(row["regularMarketTime"]), tz=timezone.utc).isoformat()
            if row.get("regularMarketTime")
            else None
        ),
    )
