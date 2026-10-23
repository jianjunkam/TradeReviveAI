# TradeRevive AI

A trading-recovery platform for people who have lost money trading: it shows what the market
did, what your own trades did, and where the leak is.

Built from the GigaLab blueprint (`blueprint.json`) — FastAPI + PostgreSQL + plain
HTML/CSS/JS, no build step and no frontend framework.

---

## What works today

| Page | What it is | Data source |
|---|---|---|
| `/` | **US market** — breadth, markets overview, a rules-based screen, 100 stocks sortable | Yahoo Finance |
| `/journal` | **Trade journal** — net P&L, win rate, profit factor, equity curve, month calendar, mistake rules | computed from papertrades |
| `/papertrade` | **Simulated trading** — buy/sell US stocks at the latest real price | Yahoo price, simulated cash |
| `/diagnosis` | **Assistant** — a Flowise chatflow that explains metrics and market data | external Flowise instance |
| `/app` | The authenticated workspace (magic link + TOTP) | Postgres |

The demo pages are not hardcoded sample data. Where a number is unknown it shows `—`, never a
plausible-looking zero.

---

## Quick start

Requires **Python 3.12** and an internet connection — prices come from Yahoo Finance over
HTTPS, with no account and no gateway. Previously
`127.0.0.1:11111`. Postgres is only needed for `/app` (sign-in).

```bash
git clone <this repo>
cd traderevive-ai-build-pack

python -m venv .venv
source .venv/Scripts/activate      # Windows git-bash; Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env               # then edit it — see Settings
```

Start it:

```bash
./start.sh          # Windows: double-click start.bat
```

The script checks the virtualenv (creating it if needed), makes `.env` if it is missing,
brings up Postgres when Docker is available, checks the price feed, and picks a
free port — then serves the app with **no login page**. `PORT=8080 ./start.sh` overrides the
port.

Open <http://127.0.0.1:8000>.

(The raw command still works if you prefer: `uvicorn app.main:app --port 8000`, but it will
put the login page back in front of `/app` unless `REQUIRE_SIGN_IN=false` is exported.)

### Minimum `.env` for the demo

```
APP_SECRET=<any long random string>
ENVIRONMENT=development
PUBLIC_DASHBOARD=true
```

### Postgres (only for /app, sign-in)

```bash
docker compose up -d                # postgres:16 on port 5433
export DATABASE_URL="postgresql+psycopg://traderevive:traderevive@localhost:5433/traderevive_test"
alembic upgrade head
```

Without `DATABASE_URL` the app still starts in development and keeps auth in memory.

### Paper account with history

A new account has no closed trades, so the journal starts empty. Seed it from real historical
closes:

```bash
./.venv/Scripts/python.exe scripts/seed_paper.py --per-symbol 6
```

It resets the paper account first, so it is repeatable. Every fill is priced from an actual
daily close returned by Yahoo Finance.

---

## Settings

All settings come from `.env` (see `.env.example`). The ones that matter:

| Variable | Default | Meaning |
|---|---|---|
| `APP_SECRET` | — | **Required.** Signs the session cookie and magic links. |
| `ENVIRONMENT` | `production` | Only `development` relaxes cookies and enables `/docs`. Deliberately safe by default. |
| `DEMO_CLOSED` | `false` | Set `true` to close the demo pages and serve the sign-in card. |
| `DEEPSEEK_API_KEY` | — | Key for the journal's AI section. Empty → Flowise fallback → "no model configured". |
| `REQUIRE_SIGN_IN` | `true` | Require the sign-in flow for `/app`. `false` removes the login page. |
| `DEMO_SIGN_IN` | `true` | Show the "enter the demo account" button on the sign-in card. |
| `PUBLIC_POSITIONS` | `false` | Include the broker account's open positions in the public API. |
| `DATABASE_URL` | — | Required outside development. |
| `MARKET_TOP_N` | `100` | How many stocks the dashboard lists, ranked by market value. |
| `MARKET_REFRESH_SECONDS` | `30` | How often the market is re-read. |
| `PAPER_STARTING_CASH` | `100000` | Simulated starting cash. |

---

## Hosting checklist

A fresh host serves the sign-in page, not the demo, until these are set:

```bash
APP_SECRET=<long random string>      # required, or the app will not start
ENVIRONMENT=development              # or production + DATABASE_URL
```

The demo pages are public by default, so `/` is the dashboard with no further setup.

To remove the login page entirely — `/app` opens as the demo account and `/sign-in` redirects
into the workspace — set:

```bash
REQUIRE_SIGN_IN=false
```

Without it, `/app` still asks for the sign-in flow (the product's real behaviour, and what the
M1 acceptance tests assert). `DEMO_CLOSED=true` closes the demo pages; and `PUBLIC_POSITIONS=true` adds your broker
account's open positions to `/api/public/market`.

`PUBLIC_DASHBOARD` is no longer read. It used to gate the demo pages, and a stale
`PUBLIC_DASHBOARD=false` in a deployed `.env` put the whole product behind a login page whose
email never arrives — so the gate moved to an opt-out flag instead.

Two things a hosted copy will not have, by design:

- **No live socket.** Prices arrive over HTTPS, so the header says "Yahoo · may be delayed"
  rather than "live", and a failed fetch names the feed instead of showing a price.
- **No brokerage positions.** Yahoo holds no account: `/api/broker/positions` says so, and the
  paper book is the only portfolio in the product.
- **No trade history.** `data/paper.json` is gitignored, so a new host has an empty journal.
  `demo/paper_seed.json` is loaded instead on first boot — trades at real historical prices,
  labelled "sample account" in the journal and on the papertrade page. Delete that file to
  start from zero.

---

## ⚠️ Before hosting this publicly

The demo pages are open to anyone who can reach the port. What they contain:

- live quotes and the market table — fine, that is public market data;
- the papertrading account and journal — simulated money, harmless;
- **your broker account's open positions** — withheld unless `PUBLIC_POSITIONS=true`.

Positions default to private: `/api/public/market` returns them only when the operator sets
`PUBLIC_POSITIONS=true`, and Yahoo holds no positions at all, so there is no book to publish
in any case. Setting it would only matter with a broker that has an account. Previously
accident. Set `PUBLIC_DASHBOARD=false` to close the demo pages entirely.

There is no user authentication on the four demo pages by design; the authenticated product
lives at `/app`.

---

## Tests

```bash
./.venv/Scripts/python.exe -m pytest -q
```

Everything passes except 32 placeholders for future milestones (`F3`–`F6` and the quality
targets), which are marked `Not written yet:` — the M0 gate test asserts exactly that, so the
suite is honest rather than green by omission.

No test touches your broker or the network: the suite uses a fake broker and an unstarted
market cache.

---

## Layout

```
app/
  main.py            create_app: routes, middleware, dependency wiring
  config.py          Settings (pydantic-settings, .env)
  permissions.py     permission matrix, @permit/@public, deny-by-default guard
  market.py          whole-market cache: sweep, rank, paginate
  paper.py           paper trading engine (Decimal money, JSON store)
  broker/            Yahoo Finance adapter + fake for tests
  routes/            auth, pages, admin, trades, broker, public, paper, journal
static/              market, journal, papertrade, diagnosis pages + their JS
migrations/          Alembic
scripts/             seed_paper.py
tests/               unit + acceptance
docs/                the build pack (AGENTS.md, BUILD_PLAN.md, STACK.md, ...)
```

## Known limits

- Sign-in is magic link + TOTP only. Email delivery is a console sender in development (the
  link prints to the terminal); no SMTP provider is wired.
- The journal's analytics come from the paper account. Reading a real broker's trade history
  is not built.
- Milestones F3–F6 (analytics engine, mistake detection, AI reports, quality targets) are
  still placeholders.
- Paper fills ignore slippage, commission, tax and liquidity, so results are optimistic by
  construction — and the page says so.
- Nothing here can place a real order: no endpoint reaches a trading context.

---

## About the build pack

This repository started as a GigaLab Module 8 (SaaS Builder Lab) pack, 2026-10-22. The
original notes are kept because `blueprint.json` is still the source of truth for
requirements and the acceptance tests.

> `blueprint.json` is the source of truth: every requirement, choice and target as data. The
> documents in `docs/` explain it, and the tests in the acceptance folder fail until each
> feature is built.
>
> 1. Put these files in an empty folder and start a Git repository there (`git init`).
> 2. Copy `.env.example` to `.env` and fill it in. Never commit `.env`.
> 3. Open the folder in your coding agent (Claude Code reads `CLAUDE.md`, Codex/Cursor read
>    `AGENTS.md`, Gemini CLI reads `GEMINI.md`).
> 4. Start with milestone M0 in `docs/BUILD_PLAN.md`.
> 5. One milestone per session. Record each in GigaLab's Build guide tab.
> 6. To change a requirement or the stack: change it in GigaLab, download the pack again, and
>    copy the new `blueprint.json` and `docs/` over the old ones.

## Licence / attribution

Coursework project. Market data from Yahoo Finance (unofficial endpoints, may be delayed). The
diagnosis assistant runs on a separate Flowise instance. Not financial advice.


## Market data: Yahoo Finance

Prices come from Yahoo Finance over HTTPS. There is no gateway to install, no brokerage
account on the host, and nothing native to compile — which is what makes the project
deployable by someone else.

| | |
|---|---|
| Quotes | `v7/finance/quote`, batched, with a cookie + crumb handshake |
| Universe | Yahoo's screener, the largest US companies by market cap |
| Markets page | Indices, commodities, currencies, bonds and crypto (`/api/public/overview`) |
| Missing change % | Derived from last/prev close, or left `null` — never `0.00%` |
| Positions | None. Paper trading keeps its own book |
| Caveat | Unofficial endpoint, no contract; the header says **"Yahoo · may be delayed"** |

Honesty rules: a missing price renders `—`, never `0.00%`; a source that cannot be reached
says so instead of showing yesterday's number as today's; a feed that is not an exchange
feed never wears the word "live".
