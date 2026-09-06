#!/usr/bin/env python3
"""The hardware -> graph seam: web/data/bins.json from the API's bin seed.

    python3 ml/load/load_bins.py [--dry-run]

`services/api/seed/depot_bins.json` is the source of truth for which physical bin
holds what — the API serves it, the firmware's NODE_ID must match an entry in it,
and `covers_drugs` is what makes "this bin is condemned" mean "these six drugs are
affected". The graph side of that seam, `web/data/bins.json`, was `[]`, so
`loadGraph()` reported 0 bins and nothing in the graph knew a depot existed.

Two shapes, deliberately different, which is why this file exists:

    seed (API)   node_id, covers_drugs as BARE NAMES     ["amoxicillin", ...]
    bins.json    id,      covers_drugs as DRUG IDS       ["drug:amoxicillin", ...]

`validate.py` enforces the drug: prefix ("covers_drugs must hold drug: ids") and
counts them as node references, so a typo here surfaces as a dangling reference
rather than as a bin that silently covers nothing. The API keeps bare names
because the device and the storage evaluator have no notion of a graph node.

Every name must resolve to a declared drug node or this refuses to write — a bin
covering a drug the graph has never heard of is the exact failure the validator's
reference check exists to catch.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import io_helpers as io  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED = REPO_ROOT / "services" / "api" / "seed" / "depot_bins.json"
OUT = io.DATA_DIR / "bins.json"
DRY = "--dry-run" in sys.argv


def main() -> int:
    if not SEED.exists():
        print(f"no seed at {SEED} — nothing to do")
        return 0

    declared = set()
    for f in ("nodes.openfda.json", "nodes.curated.json", "nodes.signals.json"):
        p = io.DATA_DIR / f
        if p.exists():
            declared |= {n["id"] for n in json.loads(p.read_text())}

    bins, missing = [], []
    for b in json.loads(SEED.read_text()):
        covers = []
        for name in b.get("covers_drugs") or []:
            # The seed carried BARE NAMES until route-ui switched it to `drug:` ids
            # so the API and the graph agree without a translation step. Accept both:
            # io.drug_id() on an already-prefixed id yields `drug:drug-oxacillin`,
            # which is why step 10/10 of run_all.sh started refusing to write.
            drug_id = name if str(name).startswith("drug:") else io.drug_id(name)
            if drug_id not in declared:
                missing.append((b["node_id"], name, drug_id))
                continue
            covers.append(drug_id)
        bins.append({
            "id": b["node_id"], "label": b.get("label"), "covers_drugs": covers,
            # ISO-2 of the point of interest the bin sits in. Depots are local to a
            # country, and the console lists a bin only under its own.
            "country": b.get("country"),
        })

    for node_id, name, drug_id in missing:
        print(f"  ERROR {node_id}: covers_drugs {name!r} -> {drug_id} is not a declared node")
    if missing:
        print("refusing to write — fix the seed or load the missing drug nodes first")
        return 1

    for b in bins:
        print(f"  {b['id']:24} {len(b['covers_drugs'])} drug(s)  {b['label']}")

    if DRY:
        print(f"\n--dry-run: {len(bins)} bin(s) not written")
        return 0

    previous = OUT.read_text() if OUT.exists() else None
    OUT.write_text(json.dumps(bins, indent=2, ensure_ascii=False) + "\n")
    result = io.run_validate()
    if result.returncode != 0:
        if previous is None:
            OUT.unlink(missing_ok=True)
        else:
            OUT.write_text(previous)
        print(f"rolled back — contract violation:\n{result.stderr.strip()}")
        return 1
    print(f"\nwrote {len(bins)} bin(s) -> {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
