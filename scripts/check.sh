#!/usr/bin/env bash
# Cheap sanity pass. Non-blocking by design — it reports, it does not gate.
set -uo pipefail
cd "$(dirname "$0")/.."

fail=0
ok()  { printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad() { printf '  \033[31m✗\033[0m %s\n' "$1"; fail=1; }

echo "contracts parse:"
for f in contracts/schemas/*.json; do
  [ -e "$f" ] || continue
  python3 -c "import json,sys; json.load(open('$f'))" 2>/dev/null && ok "$f" || bad "$f is not valid JSON"
done
if [ -f contracts/openapi.yaml ]; then
  # System python3 usually has no pyyaml, so this check quietly never ran. The ml
  # venv does have it (ml/requirements.txt), so try that before giving up.
  PY_YAML=python3
  for cand in ml/.venv/bin/python services/api/.venv/bin/python; do
    [ -x "$cand" ] && "$cand" -c "import yaml" 2>/dev/null && { PY_YAML="$cand"; break; }
  done
  if "$PY_YAML" -c "import yaml" 2>/dev/null; then
    "$PY_YAML" -c "import yaml; yaml.safe_load(open('contracts/openapi.yaml'))" 2>/dev/null \
      && ok "contracts/openapi.yaml" || bad "contracts/openapi.yaml is not valid YAML"
  else
    echo "  · openapi.yaml unchecked (no pyyaml — run ./scripts/bootstrap.sh)"
  fi
fi

echo ".env keys:"
if [ -f .env ]; then
  missing=0
  while IFS= read -r k; do
    grep -q "^${k}=" .env || { bad ".env is missing $k (present in .env.example)"; missing=1; }
  done < <(grep -E '^[A-Z_][A-Z0-9_]*=' .env.example | cut -d= -f1)
  [ $missing -eq 0 ] && ok "all .env.example keys present in .env"
else
  bad ".env not found — run ./scripts/bootstrap.sh"
fi

exit $fail
