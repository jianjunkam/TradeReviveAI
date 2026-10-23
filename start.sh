#!/usr/bin/env bash
# TradeRevive AI — one-command startup.
#
#   ./start.sh              # default port 8000
#   PORT=8080 ./start.sh    # any other port
#
# What it does, in order: finds or creates the virtualenv, makes sure .env exists with a
# secret, brings up Postgres if Docker is available, tells you whether the broker gateway is
# reachable, picks a free port, then serves the app with no login page.
#
# Every optional step reports and continues: the demo pages do not need Postgres, and they do
# not need OpenD either — they say what is missing instead of inventing numbers.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT" || exit 1

PORT="${PORT:-8000}"
BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
RED=$'\033[31m'; RESET=$'\033[0m'

ok()   { printf '  %sok%s   %s\n'   "$GREEN" "$RESET" "$1"; }
warn() { printf '  %swarn%s %s\n'   "$YELLOW" "$RESET" "$1"; }
bad()  { printf '  %sfail%s %s\n'   "$RED" "$RESET" "$1"; }
step() { printf '\n%s%s%s\n' "$BOLD" "$1" "$RESET"; }

printf '%s\n' "${BOLD}TradeRevive AI${RESET} ${DIM}starting…${RESET}"

# ---------------------------------------------------------------- 1. interpreter
step "1. Python"

if [ -x ".venv/Scripts/python.exe" ]; then
  PY=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  warn "no .venv yet — creating one"
  if command -v py >/dev/null 2>&1; then
    py -3.12 -m venv .venv || py -3 -m venv .venv
  else
    python3 -m venv .venv || python -m venv .venv
  fi
  if [ -x ".venv/Scripts/python.exe" ]; then PY=".venv/Scripts/python.exe"; else PY=".venv/bin/python"; fi
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -r requirements.txt
  ok "virtualenv created and dependencies installed"
fi

if ! "$PY" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  warn "dependencies missing — installing from requirements.txt"
  "$PY" -m pip install --quiet -r requirements.txt || { bad "pip install failed"; exit 1; }
fi
ok "$("$PY" -c 'import sys; print(sys.version.split()[0])') at $PY"

# ------------------------------------------------------------------- 2. settings
step "2. Settings (.env)"

if [ ! -f ".env" ]; then
  warn ".env is missing — creating it from .env.example with a generated secret"
  SECRET="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(48))')"
  sed "s|^APP_SECRET=.*|APP_SECRET=${SECRET}|" .env.example > .env
  ok ".env created"
else
  ok ".env found"
fi

if ! grep -qE '^APP_SECRET=.+' .env; then
  bad "APP_SECRET is empty in .env — the app will refuse to boot"
  exit 1
fi

# No login page, and the public pages on: these are exported for this run only. pytest reads
# .env, and REQUIRE_SIGN_IN=false there would make the M1 tests pass for the wrong reason.
export REQUIRE_SIGN_IN=false
export PUBLIC_DASHBOARD=true
ok "REQUIRE_SIGN_IN=false, PUBLIC_DASHBOARD=true (this run only)"

# ------------------------------------------------------------------- 3. database
step "3. Postgres (only needed for /app sign-in)"

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  if docker ps --filter name=traderevive-db --format '{{.Names}}' | grep -q traderevive-db; then
    ok "traderevive-db is already running"
  else
    if docker compose up -d --wait >/dev/null 2>&1; then
      ok "traderevive-db started on port 5433"
    else
      warn "docker compose could not start the database — continuing without it"
    fi
  fi
else
  warn "Docker is not running — the demo pages still work, sign-in does not"
  case "$(uname -s)" in
    MINGW*|MSYS*)
      if [ -f "$LOCALAPPDATA/Programs/DockerDesktop/Docker Desktop.exe" ]; then
        warn "start Docker Desktop from the Start menu if you need /app sign-in"
      fi ;;
  esac
fi

# --------------------------------------------------------------------- 4. broker
step "4. Broker gateway (moomoo OpenD)"

if "$PY" - <<'PYCODE' >/dev/null 2>&1
import socket, sys
try:
    socket.create_connection(("127.0.0.1", 11111), timeout=1.5).close()
except OSError:
    sys.exit(1)
PYCODE
then
  ok "OpenD is listening on 127.0.0.1:11111"
else
  warn "OpenD is not listening — the market table will say so; news and the journal still work"
fi

# ------------------------------------------------------------------ 5. free port
step "5. Port"

port_is_free() {
  "$PY" - "$1" <<'PYCODE' >/dev/null 2>&1
import socket, sys
s = socket.socket()
try:
    s.bind(("127.0.0.1", int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PYCODE
}

if ! port_is_free "$PORT"; then
  ORIGINAL="$PORT"
  for candidate in $(seq "$PORT" $((PORT + 20))); do
    if port_is_free "$candidate"; then PORT="$candidate"; break; fi
  done
  if [ "$PORT" = "$ORIGINAL" ]; then
    bad "ports $ORIGINAL-$((ORIGINAL + 20)) are all busy"
    exit 1
  fi
  warn "port $ORIGINAL is busy — using $PORT instead"
else
  ok "port $PORT is free"
fi

# ---------------------------------------------------------------------- 6. serve
step "6. Serving"

printf '  %sdashboard%s   http://127.0.0.1:%s/\n'   "$DIM" "$RESET" "$PORT"
printf '  %sjournal%s     http://127.0.0.1:%s/journal\n'   "$DIM" "$RESET" "$PORT"
printf '  %spapertrade%s  http://127.0.0.1:%s/papertrade\n' "$DIM" "$RESET" "$PORT"
printf '  %sdiagnosis%s   http://127.0.0.1:%s/diagnosis\n'  "$DIM" "$RESET" "$PORT"
printf '  %sworkspace%s   http://127.0.0.1:%s/app      (no login)\n' "$DIM" "$RESET" "$PORT"
printf '\n  %sCtrl-C to stop%s\n\n' "$DIM" "$RESET"

exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --reload
