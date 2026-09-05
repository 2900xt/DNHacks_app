#!/usr/bin/env bash
# Install dependencies for whichever components have picked a stack.
# Safe to re-run. Skips anything not present.
set -uo pipefail
cd "$(dirname "$0")/.."

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
skip() { printf '  \033[90m·\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }

echo "bootstrapping DNHacks_app..."

[ -f .env ] || { cp .env.example .env && ok "created .env from .env.example"; }

for d in web services/api ml firmware; do
  [ -d "$d" ] || continue
  if   [ -f "$d/pnpm-lock.yaml" ]; then (cd "$d" && pnpm install)      && ok "$d (pnpm)"
  elif [ -f "$d/package.json" ];   then (cd "$d" && npm install)       && ok "$d (npm)"
  elif [ -f "$d/pyproject.toml" ]; then (cd "$d" && (uv sync 2>/dev/null || pip install -e .)) && ok "$d (python)"
  elif [ -f "$d/requirements.txt" ]; then (cd "$d" && pip install -r requirements.txt) && ok "$d (pip)"
  elif [ -f "$d/Cargo.toml" ];     then (cd "$d" && cargo fetch)       && ok "$d (cargo)"
  elif [ -f "$d/platformio.ini" ]; then (cd "$d" && pio pkg install)   && ok "$d (platformio)"
  else skip "$d — no stack picked yet"
  fi
done

echo "done."
