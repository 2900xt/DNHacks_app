#!/usr/bin/env bash
# Rebuild the curated artifacts from scratch, in dependency order.
#
#   ml/load/run_all.sh          rebuild from empty
#   ml/load/run_all.sh --keep   re-run over whatever is already there
#
# ORDER MATTERS. load_taa and load_1260h annotate nodes that load_dmf creates:
# run them first and they silently annotate nothing. Both now exit non-zero in
# that case, but the ordering is the actual fix.
set -euo pipefail

cd "$(dirname "$0")/../.."
PY=python3
VENV=ml/.venv/bin/python
[ -x "$VENV" ] || { echo "run: python3 -m venv ml/.venv && ml/.venv/bin/pip install -r ml/requirements.txt"; exit 1; }

if [ "${1:-}" != "--keep" ]; then
  echo "resetting curated artifacts to empty"
  for f in nodes.curated edges.curated compliance; do printf '[]\n' > "web/data/$f.json"; done
fi

echo "1/8 precursor node + six-penicillin fan-out";        $PY   ml/load/load_precursor_edges.py
echo "2/8 DMF register (creates company + country nodes)"; $VENV ml/load/load_dmf.py
echo "3/8 DECRS (real country + FEI on companies)";        $PY   ml/load/load_decrs.py
echo "4/8 EO 13944 (critical mark on drug nodes)";         $VENV ml/load/load_eo13944.py
echo "5/8 EO 14336 (citation only — 0 nodes by design)";   $PY   ml/load/load_eo14336.py
echo "6/8 TAA pass/fail on country nodes";                 $PY   ml/load/load_taa.py
echo "7/8 1260H flag on company nodes";                    $PY   ml/load/load_1260h.py
echo "8/8 compliance engine (company -> country -> TAA)";  $PY   ml/compliance.py

echo; echo "validating"; $PY ml/load/validate.py

$PY - <<'EOF'
import json, sys
n = json.load(open("web/data/nodes.curated.json"))
c = {r["node_id"] for r in json.load(open("web/data/compliance.json"))}
need = [x["id"] for x in n if x["type"] in ("company", "country")]
missing = [x for x in need if x not in c]
print(f"\ncompliance coverage: {len(need) - len(missing)}/{len(need)} company+country nodes")
if missing:
    print("MISSING:", *missing, sep="\n  ")
    sys.exit(1)
EOF
