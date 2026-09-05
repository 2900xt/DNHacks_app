#!/usr/bin/env bash
# Run every component that defines a dev entrypoint, in parallel.
# Ctrl-C kills all of them.
set -uo pipefail
cd "$(dirname "$0")/.."

pids=()
cleanup() { trap - INT TERM; kill "${pids[@]}" 2>/dev/null; }
trap cleanup INT TERM EXIT

start() { # start <label> <cmd...>
  local label="$1"; shift
  echo "→ $label: $*"
  ( "$@" 2>&1 | sed "s/^/[$label] /" ) &
  pids+=($!)
}

for d in services/api ml web; do
  [ -d "$d" ] || continue
  if   [ -f "$d/package.json" ] && grep -q '"dev"' "$d/package.json" 2>/dev/null; then
    start "$d" bash -c "cd '$d' && npm run dev"
  elif [ -x "$d/dev.sh" ]; then
    start "$d" "$d/dev.sh"
  elif [ -f "$d/Cargo.toml" ]; then
    start "$d" bash -c "cd '$d' && cargo run"
  fi
done

if [ ${#pids[@]} -eq 0 ]; then
  echo "nothing to run yet — no component defines a dev entrypoint."
  echo "add one as 'npm run dev', a Cargo.toml, or an executable <component>/dev.sh"
  exit 0
fi

wait
