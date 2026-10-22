"""moomoo OpenD — the real broker connection.

OpenD is a local gateway that you run yourself and sign in to with your moomoo account.
This module talks to it on 127.0.0.1:11111 using the official `moomoo-api` SDK.

What it will never do: invent a price. Every method either returns what OpenD reported or
raises `BrokerUnavailable` with a sentence the user can act on. The dashboard shows "not
connected" rather than a plausible-looking number, because a trader cannot tell a stale
sample from a live quote.

Requirements on the machine running this:
  * OpenD installed, running, and signed in (port 11111 by default)
  * market-data permission for the market you ask for (Bursa Malaysia real-time is a paid
    subscription; without it OpenD answers with an error or delayed data)
  * `pip install moomoo-api` (already in requirements.txt)
"""

from __future__ import annotations

import socket
import threading
import time
from datetime import datetime, timezone

from app.broker.base import (
    BrokerStatus,
    BrokerUnavailable,
    MarketRow,
    Position,
    Quote,
    SymbolInfo,
    utc_now,
)

#: moomoo codes carry their market: US.AAPL, MY.5225, HK.00700.
MARKET_PREFIXES = ("US", "HK", "MY", "SG", "JP", "AU", "SH", "SZ")

#: Exchanges whose quotes this account can actually read. US_PINK (5,909 tickers) is
#: excluded: one OTC code in a batch fails the WHOLE batch with "US OTC market quote is
#: not available", which would make the rest of the market unreadable.
LISTED_EXCHANGES = {"US_NASDAQ", "US_NYSE", "US_AMEX"}

#: The trading firm per market. Guessing `FUTU{market}` is wrong for US (FUTUINC) and
#: HK (FUTUSECURITIES), and OpenD answers those with "no available real accounts".
SECURITY_FIRM = {
    "US": "FUTUINC",
    "HK": "FUTUSECURITIES",
    "SG": "FUTUSG",
    "MY": "FUTUMY",
    "JP": "FUTUJP",
    "AU": "FUTUAU",
    "CA": "FUTUCA",
}


def _check_symbol(symbol: str) -> str:
    code = symbol.strip().upper()
    if "." not in code or code.split(".", 1)[0] not in MARKET_PREFIXES:
        raise BrokerUnavailable(
            f"{symbol!r} is not a moomoo code. Use MARKET.SYMBOL, for example "
            "US.AAPL or MY.5225 (Bursa Malaysia)."
        )
    return code


class MoomooBroker:
    """Read-only access to what OpenD is reporting."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 11111,
        *,
        market: str = "MY",
        trade_market: str | None = None,
        trade_env: str = "SIMULATE",
        connect_timeout: float = 1.5,
        call_timeout: float = 8.0,
    ) -> None:
        self.host = host
        self.port = port
        #: The market quotes are asked for; the symbol itself decides too.
        self.market = market.upper()
        #: The market whose trading account holds the positions. Often different from the
        #: quote market: an account can see US quotes and hold no MY trading account.
        self.trade_market = (trade_market or market).upper()
        self.trade_env = trade_env.upper()
        self.connect_timeout = connect_timeout
        self.call_timeout = call_timeout
        self._universe: list[SymbolInfo] | None = None
        self._universe_at = 0.0
        #: Status is asked for on every page render. Caching it stops each render from
        #: opening an SDK context — and every context the SDK opens leaves a thread that
        #: delays process exit, which turns a busy dashboard into a slow Ctrl-C.
        self._status_cache: BrokerStatus | None = None
        self._status_at = 0.0
        self.STATUS_TTL = 5.0

    # ------------------------------------------------------------------ status

    def status(self, *, fresh: bool = False) -> BrokerStatus:
        """Is OpenD reachable and answering? Never raises."""
        now = time.monotonic()
        if (
            not fresh
            and self._status_cache is not None
            and now - self._status_at < self.STATUS_TTL
        ):
            return self._status_cache

        result = self._probe_status()
        self._status_cache = result
        self._status_at = now
        return result

    def _probe_status(self) -> BrokerStatus:
        if not self._port_is_open():
            return BrokerStatus(
                connected=False,
                reason=(
                    f"OpenD is not listening on {self.host}:{self.port}. Start moomoo "
                    "OpenD, sign in, and check that it is running on this port."
                ),
                host=self.host,
                port=self.port,
                checked_at=utc_now(),
            )

        try:
            mm = self._sdk()
        except BrokerUnavailable as exc:
            return BrokerStatus(
                connected=False,
                reason=str(exc),
                host=self.host,
                port=self.port,
                checked_at=utc_now(),
            )

        context = None
        try:
            context = mm.OpenQuoteContext(host=self.host, port=self.port)
            ret, data = context.get_global_state()
            if ret != mm.RET_OK:
                return BrokerStatus(
                    connected=False,
                    reason=f"OpenD is running but refused the request: {data}",
                    host=self.host,
                    port=self.port,
                    checked_at=utc_now(),
                )
            return BrokerStatus(
                connected=True,
                reason=None,
                host=self.host,
                port=self.port,
                checked_at=utc_now(),
                account=None,
            )
        except Exception as exc:  # noqa: BLE001 - any SDK failure means "not usable"
            return BrokerStatus(
                connected=False,
                reason=f"OpenD did not answer correctly: {exc}",
                host=self.host,
                port=self.port,
                checked_at=utc_now(),
            )
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:  # noqa: BLE001 - closing must never mask a result
                    pass

    # ------------------------------------------------------------------ quotes

    def quote(self, symbol: str) -> Quote:
        """One snapshot for one instrument, exactly as OpenD reports it."""
        code = _check_symbol(symbol)
        self._ensure_open()
        mm = self._sdk()

        def work() -> Quote:
            context = None
            try:
                context = mm.OpenQuoteContext(host=self.host, port=self.port)
                ret, data = context.get_market_snapshot([code])
                if ret != mm.RET_OK:
                    raise BrokerUnavailable(self._explain(data, code))
                row = _first_row(data)
                if row is None:
                    raise BrokerUnavailable(f"OpenD returned no snapshot for {code}.")
                return _quote_from_row(code, row)
            except BrokerUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001
                raise BrokerUnavailable(self._explain(exc, code)) from exc
            finally:
                _close(context)

        return self._with_timeout(f"a quote for {code}", work)

    # --------------------------------------------------------------- positions

    def positions(self) -> list[Position]:
        """Open positions in the configured trading environment."""
        self._ensure_open()
        mm = self._sdk()

        def work() -> list[Position]:
            context = None
            try:
                firm = SECURITY_FIRM.get(self.trade_market, "FUTUMY")
                context = mm.OpenSecTradeContext(
                    filter_trdmarket=getattr(mm.TrdMarket, self.trade_market, mm.TrdMarket.MY),
                    host=self.host,
                    port=self.port,
                    security_firm=getattr(mm.SecurityFirm, firm, mm.SecurityFirm.FUTUMY),
                )
                ret, data = context.position_list_query(
                    trd_env=getattr(mm.TrdEnv, self.trade_env, mm.TrdEnv.SIMULATE)
                )
                if ret != mm.RET_OK:
                    raise BrokerUnavailable(self._explain(data, "positions"))
                rows = data.to_dict("records") if hasattr(data, "to_dict") else []
                return [_position_from_row(row) for row in rows]
            except BrokerUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001
                raise BrokerUnavailable(self._explain(exc, "positions")) from exc
            finally:
                _close(context)

        return self._with_timeout("positions", work)

    # ---------------------------------------------------------------- universe

    #: OpenD allows 400 codes per snapshot request and 60 requests per 30 seconds, so a
    #: 400-code batch keeps a 7,148-stock sweep to 18 requests.
    SNAPSHOT_CHUNK = 400
    #: Pacing between batches. 18 requests with a 0.4s gap spread over ~20s stays inside
    #: the documented 60-per-30s ceiling even when a second sweep starts early.
    PACE_SECONDS = 0.4
    #: A whole-market sweep is 18 batches; 8s is not enough for it.
    SWEEP_TIMEOUT = 180.0
    UNIVERSE_TIMEOUT = 30.0
    UNIVERSE_TTL = 12 * 3600.0

    def universe(self, market: str = "US") -> list[SymbolInfo]:
        """Every listed stock on a real exchange in `market`.

        OTC/PINK codes are excluded deliberately. The account has no OTC quote permission,
        and OpenD fails an ENTIRE batched snapshot when one code lacks it — 5,909 pink-sheet
        tickers would otherwise make the whole US market unreadable. `get_stock_basicinfo`
        is slow (about 3s for 13k rows), so the answer is cached.
        """
        now = time.monotonic()
        if self._universe and now - self._universe_at < self.UNIVERSE_TTL:
            return self._universe

        self._ensure_open()
        mm = self._sdk()

        def work() -> list[SymbolInfo]:
            context = None
            try:
                context = mm.OpenQuoteContext(host=self.host, port=self.port)
                ret, data = context.get_stock_basicinfo(
                    getattr(mm.Market, market.upper(), mm.Market.US),
                    mm.SecurityType.STOCK,
                )
                if ret != mm.RET_OK:
                    raise BrokerUnavailable(self._explain(data, f"the {market} stock list"))
                symbols: list[SymbolInfo] = []
                for row in data.to_dict("records"):
                    exchange = str(row.get("exchange_type") or "")
                    if exchange not in LISTED_EXCHANGES:
                        continue
                    if row.get("delisting"):
                        continue
                    if str(row.get("suspension") or "") == "Y":
                        continue
                    code = str(row.get("code") or "")
                    if not code:
                        continue
                    # US.AHT.PRG (preferred), US.CELG.RT (right), US.XYZ.WS (warrant) are
                    # separate instruments. They are real, but they are not common stock,
                    # and they crowd the movers with 99% moves on a 12c stub.
                    if code.count(".") > 1:
                        continue
                    symbols.append(
                        SymbolInfo(
                            symbol=code,
                            name=clean_name(str(row.get("name") or code)),
                            exchange=exchange.replace("US_", ""),
                        )
                    )
                return symbols
            except BrokerUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001
                raise BrokerUnavailable(self._explain(exc, f"the {market} stock list")) from exc
            finally:
                _close(context)

        symbols = self._with_timeout(
            f"the {market} stock list", work, timeout=self.UNIVERSE_TIMEOUT
        )
        self._universe = symbols
        self._universe_at = time.monotonic()
        return symbols

    # --------------------------------------------------------------- snapshots

    def snapshots(self, symbols: list[str]) -> list[MarketRow]:
        """Latest state for many instruments, in batches, over one connection.

        One bad batch is skipped rather than losing the other 35: the caller gets every row
        OpenD would give, and the count is what it is. A total failure raises, so the UI can
        say why instead of rendering an empty market.
        """
        codes = [s for s in symbols if s]
        if not codes:
            return []
        self._ensure_open()
        mm = self._sdk()
        chunk_size = self.SNAPSHOT_CHUNK

        def work() -> list[MarketRow]:
            context = None
            rows: list[MarketRow] = []
            errors: list[str] = []
            batches = [codes[i : i + chunk_size] for i in range(0, len(codes), chunk_size)]
            try:
                context = mm.OpenQuoteContext(host=self.host, port=self.port)
                for index, chunk in enumerate(batches):
                    if index:
                        # Documented ceiling: 60 requests / 30s. A tight loop trips it and
                        # OpenD then refuses every remaining batch.
                        time.sleep(self.PACE_SECONDS)
                    ret, data = context.get_market_snapshot(chunk)
                    if ret != mm.RET_OK and "high frequency" in str(data).lower():
                        time.sleep(2.0)
                        ret, data = context.get_market_snapshot(chunk)
                    if ret != mm.RET_OK:
                        errors.append(self._explain(data, f"a batch of {len(chunk)} symbols"))
                        continue
                    for row in data.to_dict("records"):
                        rows.append(_market_row_from_row(row))
            except BrokerUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001
                raise BrokerUnavailable(self._explain(exc, "market snapshots")) from exc
            finally:
                _close(context)
            if not rows and errors:
                raise BrokerUnavailable(errors[0])
            return rows

        return self._with_timeout(
            f"snapshots for {len(codes)} symbols", work, timeout=self.SWEEP_TIMEOUT
        )

    # ---------------------------------------------------------------- helpers

    def is_listening(self) -> bool:
        """True when something accepts a TCP connection on host:port (OpenD, hopefully)."""
        return self._port_is_open()

    def _port_is_open(self) -> bool:
        """A fast, dependency-free check that beats waiting on the SDK's timeout."""
        try:
            with socket.create_connection(
                (self.host, self.port), timeout=self.connect_timeout
            ):
                return True
        except OSError:
            return False

    def _ensure_open(self) -> None:
        """Refuse in milliseconds instead of letting the SDK retry for minutes.

        The SDK's own connect loop backs off and retries indefinitely when OpenD is
        absent, which would hang a web request. This check runs first, every time.
        """
        if not self._port_is_open():
            raise BrokerUnavailable(
                f"OpenD is not listening on {self.host}:{self.port}. Start moomoo OpenD, "
                "sign in with your moomoo account, and leave it running."
            )

    def _with_timeout(self, what: str, work, timeout: float | None = None):
        """Run an SDK call on a daemon thread and stop waiting after the limit.

        A blocked SDK call cannot be cancelled, so on timeout the worker is abandoned
        rather than joined: the request returns an honest error instead of hanging. The
        thread is a daemon on purpose — `ThreadPoolExecutor` registers an exit hook that
        joins its workers, which turns one stuck connection into a process that will not
        shut down. `timeout` is for calls that legitimately take longer: a whole-market
        sweep is dozens of batched requests, not one.
        """
        limit = self.call_timeout if timeout is None else timeout
        outcome: dict[str, object] = {}

        def runner() -> None:
            try:
                outcome["value"] = work()
            except BaseException as exc:  # noqa: BLE001 - surfaced to the caller below
                outcome["error"] = exc

        thread = threading.Thread(target=runner, name="moomoo-call", daemon=True)
        thread.start()
        thread.join(limit)
        if thread.is_alive():
            raise BrokerUnavailable(
                f"OpenD accepted the connection but did not answer {what} within "
                f"{limit:g}s. It may still be starting, or not signed in."
            )
        error = outcome.get("error")
        if error is not None:
            raise error  # type: ignore[misc]
        return outcome.get("value")

    @staticmethod
    def _sdk():
        try:
            import moomoo  # noqa: PLC0415 - lazy: the app must start without the SDK
        except ImportError as exc:  # pragma: no cover - depends on the machine
            raise BrokerUnavailable(
                "The moomoo SDK is not installed in this environment. "
                "Run: pip install moomoo-api"
            ) from exc

        # The SDK's internal threads are non-daemon by default, so ONE open connection is
        # enough to keep the process alive at exit: Ctrl-C appears to hang, and a test run
        # never returns. This is the SDK's own supported switch, and it is idempotent.
        try:
            moomoo.SysConfig.set_all_thread_daemon(True)
        except Exception:  # noqa: BLE001 - an older SDK may not expose it
            pass
        return moomoo

    def _explain(self, payload, what: str) -> str:
        """Turn OpenD's error into something a trader can act on."""
        text = str(payload)
        lowered = text.lower()
        if "no permission" in lowered or "permission" in lowered or "quota" in lowered:
            return (
                f"OpenD refused {what}: this account has no market-data permission for "
                f"that market. Grant the quote permission in the moomoo app (Quotes → "
                f"market data), then retry. ({text})"
            )
        if "type of environment param" in lowered:
            return (
                f"OpenD has no {self.trade_env} trading account for {self.trade_market}. "
                "Moomoo MY has no paper-trading account, and the SDK reports that as a "
                "parameter error. Set OPEND_TRADE_MARKET / OPEND_TRADE_ENV to an account "
                "you actually hold — for example US + SIMULATE. "
                f"({text})"
            )
        if "no available real accounts" in lowered or "no available" in lowered:
            return (
                f"No {self.trade_market} trading account is linked to this moomoo ID, so "
                "there are no positions to read. Point OPEND_TRADE_MARKET at a market you "
                f"hold an account in (US or HK), or open one in the app. ({text})"
            )
        if "not logged" in lowered or "login" in lowered:
            return f"OpenD is running but not signed in. Sign in to OpenD and retry. ({text})"
        return f"OpenD could not answer for {what}: {text}"


def _close(context) -> None:
    if context is None:
        return
    try:
        context.close()
    except Exception:  # noqa: BLE001 - closing must never mask a result
        pass


def _first_row(data):
    """The SDK returns a pandas DataFrame (or a dict on old versions)."""
    if data is None:
        return None
    if hasattr(data, "to_dict"):
        records = data.to_dict("records")
        return records[0] if records else None
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict):
        return data
    return None


def _number(row: dict, *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def clean_name(name: str) -> str:
    """Collapse moomoo's padded names. Never rewrite them: a surname is not a typo."""
    return " ".join(name.split())


def _market_row_from_row(row: dict) -> MarketRow:
    """One market row from a batched snapshot. Missing prices stay None, not zero."""
    code = str(row.get("code") or "")
    last = _number(row, "last_price", "cur_price")
    previous_close = _number(row, "prev_close_price")
    change_rate = _number(row, "change_rate", "change_pct")
    if change_rate is None and last is not None and previous_close:
        change_rate = round((last - previous_close) / previous_close * 100, 2)
    volume = _number(row, "volume")
    return MarketRow(
        symbol=code,
        name=clean_name(str(row.get("name") or code)),
        last_price=last,
        previous_close=previous_close,
        change_rate=change_rate,
        volume=int(volume) if volume is not None else None,
        turnover=_number(row, "turnover"),
        market_cap=_number(row, "total_market_val"),
        pe_ratio=_number(row, "pe_ratio"),
        bid=_number(row, "bid_price", "bid"),
        ask=_number(row, "ask_price", "ask"),
        updated_at=str(row.get("update_time") or "") or None,
    )


def _quote_from_row(code: str, row: dict) -> Quote:
    last = _number(row, "last_price", "cur_price")
    if last is None:
        raise BrokerUnavailable(
            f"OpenD returned no last price for {code}; the instrument may be suspended "
            "or the subscription may not cover it."
        )
    previous_close = _number(row, "prev_close_price", "prev_close") or 0.0

    # The snapshot carries no change_rate (verified against OpenD 10.11), so it is derived
    # from the broker's own last and previous close. Showing 0.0% instead would be a lie.
    change_rate = _number(row, "change_rate", "change_pct")
    if change_rate is None:
        change_rate = (
            round((last - previous_close) / previous_close * 100, 2)
            if previous_close
            else 0.0
        )

    return Quote(
        symbol=str(row.get("code") or code),
        name=str(row.get("name") or row.get("stock_name") or code),
        last_price=last,
        previous_close=previous_close,
        change_rate=change_rate,
        volume=int(_number(row, "volume") or 0),
        bid=_number(row, "bid_price", "bid"),
        ask=_number(row, "ask_price", "ask"),
        updated_at=str(row.get("update_time")) if row.get("update_time") else None,
        # OpenD does not state freshness per snapshot; None means "not reported".
        delayed=None,
    )


def _position_from_row(row: dict) -> Position:
    return Position(
        symbol=str(row.get("code") or ""),
        name=str(row.get("stock_name") or row.get("code") or ""),
        quantity=float(row.get("qty") or 0),
        cost_price=float(row.get("cost_price") or 0),
        market_price=float(row.get("nominal_price") or 0),
        market_value=float(row.get("market_val") or 0),
        unrealised_pl=float(row.get("pl_val") or 0),
    )
