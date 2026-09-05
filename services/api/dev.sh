#!/usr/bin/env bash
# Picked up automatically by ../../scripts/dev.sh
set -euo pipefail
cd "$(dirname "$0")"

# .env supplies DEFAULTS. Anything already in the environment wins — otherwise
# `API_PORT=8801 ./dev.sh` silently starts on whatever .env says, which is a
# genuinely confusing five minutes at 4am.
if [ -f ../../.env ]; then
  while IFS='=' read -r k v; do
    [[ "$k" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
    [ -n "${!k:-}" ] || export "$k=$v"
  done < <(grep -E '^[A-Z_][A-Z0-9_]*=' ../../.env)
fi

# Arch/Debian ship externally-managed Pythons, so a venv is not optional here.
if [ ! -x .venv/bin/python ]; then
  echo "→ creating services/api/.venv"
  python3 -m venv .venv && ./.venv/bin/pip install -q -r requirements.txt
fi

exec ./.venv/bin/python -m uvicorn app:app \
  --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}" --reload
