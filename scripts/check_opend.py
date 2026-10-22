"""Is OpenD actually ready? Run this after starting it.

    ./.venv/Scripts/python.exe scripts/check_opend.py
    ./.venv/Scripts/python.exe scripts/check_opend.py --symbol US.AAPL

Checks, in order, each layer the app depends on:

  1. the SDK is installed and which version (it must match your OpenD's version)
  2. OpenD is listening on the configured host:port
  3. OpenD answers and is signed in
  4. a real quote for one symbol comes back
  5. positions are readable (SIMULATE by default; set OPEND_TRADE_ENV=REAL for live)

Exit code 0 means the app's broker card will show "live". Anything else prints the exact
reason, and the app will show the same sentence instead of a number.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.broker.base import BrokerUnavailable  # noqa: E402
from app.broker.moomoo import MoomooBroker  # noqa: E402
from app.config import get_settings  # noqa: E402

OK = "PASS"
BAD = "FAIL"
WARN = "WARN"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the moomoo OpenD connection")
    parser.add_argument("--symbol", default="MY.5225", help="MARKET.SYMBOL to quote")
    parser.add_argument(
        "--watch",
        type=float,
        default=0,
        metavar="SECONDS",
        help="keep printing the quote every N seconds (Ctrl-C to stop)",
    )
    args = parser.parse_args()

    settings = get_settings()
    failures = 0

    print("1) SDK")
    try:
        import moomoo

        version = getattr(moomoo, "__version__", "unknown")
        print(f"   {OK} moomoo-api {version} — must match your OpenD version (docs v10.11)")
    except ImportError:
        print(f"   {BAD} moomoo-api is not installed. Run: pip install -r requirements.txt")
        return 1

    broker = MoomooBroker(
        settings.opend_host,
        settings.opend_port,
        market=settings.opend_market,
        trade_market=settings.opend_trade_market,
        trade_env=settings.opend_trade_env,
    )
    print(f"   configured: {settings.opend_host}:{settings.opend_port} "
          f"| quote market {settings.opend_market} "
          f"| positions {settings.opend_trade_market}/{settings.opend_trade_env}")

    print("2) OpenD reachable")
    if not broker.is_listening():
        print(f"   {BAD} nothing is listening on {settings.opend_host}:{settings.opend_port}")
        print("        Start moomoo OpenD, sign in with your moomoo ID, and leave it running.")
        print("        Its window shows the IP and Port it listens on — they must match the above.")
        return 1
    print(f"   {OK} port {settings.opend_port} is open")

    print("3) OpenD answers")
    status = broker.status()
    if not status.connected:
        print(f"   {BAD} {status.reason}")
        return 1
    print(f"   {OK} OpenD answered (logged in)")

    print(f"4) quote {args.symbol}")
    try:
        quote = broker.quote(args.symbol)
        print(f"   {OK} {quote.symbol} {quote.name} last={quote.last_price} "
              f"prev_close={quote.previous_close} change={quote.change_rate}% "
              f"vol={quote.volume} at {quote.updated_at}")
        print("        If this is delayed rather than live, check the market-data "
              "subscription for this market in the moomoo app.")
    except BrokerUnavailable as exc:
        failures += 1
        print(f"   {BAD} {exc}")

    print("5) positions")
    try:
        positions = broker.positions()
        print(f"   {OK} {len(positions)} position(s) in {broker.trade_env}")
        for position in positions[:5]:
            print(f"        {position.symbol} qty={position.quantity} "
                  f"cost={position.cost_price} market={position.market_price} "
                  f"pl={position.unrealised_pl}")
    except BrokerUnavailable as exc:
        failures += 1
        print(f"   {WARN} {exc}")
        print("        Read-only quotes still work. Positions need the trading "
              "permission for this market and the right OPEND_TRADE_ENV.")

    print()
    if failures:
        print(f"{failures} check(s) failed. The app will show these reasons, not invented numbers.")
        return 1

    if args.watch > 0:
        print(f"Watching {args.symbol} every {args.watch:g}s — Ctrl-C to stop.")
        print("Outside market hours the price stays at the last close; that is correct.")
        try:
            while True:
                try:
                    live = broker.quote(args.symbol)
                    print(f"   {live.updated_at}  last={live.last_price}  "
                          f"bid={live.bid} ask={live.ask} vol={live.volume}")
                except BrokerUnavailable as exc:
                    print(f"   {exc}")
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("stopped")
        return 0

    print("All checks passed — open /app and the broker card will read 'live'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
