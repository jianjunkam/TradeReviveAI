#!/usr/bin/env bash
# Run the demo locally with no login page.
#
# The flags are exported here instead of living in .env on purpose: pytest reads .env, and
# REQUIRE_SIGN_IN=false would let the M1 acceptance tests pass for the wrong reason.
set -euo pipefail

cd "$(dirname "$0")/.."

# Windows venv layout first, then the POSIX one.
if [ -x ".venv/Scripts/python.exe" ]; then
  PY=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  echo "No virtualenv found. Create it first:"
  echo "  python -m venv .venv && ./.venv/Scripts/python.exe -m pip install -r requirements.txt"
  exit 1
fi

if [ ! -f ".env" ]; then
  echo "No .env yet — copying .env.example. Set APP_SECRET before going further."
  cp .env.example .env
  exit 1
fi

# Straight into the product: no sign-in card, /app opens as the demo account.
export REQUIRE_SIGN_IN=false
export PUBLIC_DASHBOARD=true

PORT="${PORT:-8000}"
echo "TradeRevive AI on http://127.0.0.1:${PORT}  (no login — /app opens as the demo account)"
exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --reload
