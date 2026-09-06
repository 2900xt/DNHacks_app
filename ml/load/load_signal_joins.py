#!/usr/bin/env python3
"""Layer 3 — join Parth's Layer 1c signal facilities into the graph.

    python3 ml/load/load_signal_joins.py            # write the joins
    python3 ml/load/load_signal_joins.py --dry-run  # print, write nothing

Why this exists
---------------
`ml/signals/` emitted 853 facility nodes carrying 1,318 signals, and 6 edges.
So 98.6% of the signal evidence sat on nodes with no edges at all — present in
`nodes.signals.json`, unreachable from the graph. Beat 4 could show 12 signals
out of 1,318, and `facility:fei:3003196232` (CSPC Zhongnuo) — the freshest of
the three anchors in `cascade_rules.py`, and the only one young enough to fire
the 90-day event window — had zero edges.

Two joins, both from keys already on the nodes. Neither invents a fact.

1. INGREDIENT -> DRUG.  The OASIS/inspection loaders tag each facility with the
   ingredients FDA records name for it. Where that tag is one of our drug nodes,
   emit `drug:X --produced_by--> facility:Y`.

   Direction matches `precursor:6-apa --produced_by--> company:X`: src is the
   substance, dst is who makes it. The cascade walks OUTGOING edges, so this is
   the direction that makes the facility reachable from the fan-out.

   Only AMOXICILLIN and AMPICILLIN are mapped. PENICILLIN (10 facilities) is a
   class, not a drug, and has no node; CEPHALOSPORIN and AZITHROMYCIN are
   outside the 6-APA story. Mapping those would be inventing nodes to raise a
   count.

2. INVERSE OF operated_by.  `edges.signals.json` asserts
   `facility --operated_by--> company`, which points AGAINST the traversal
   direction, so a signal-bearing facility hanging off a producer was invisible
   to the cascade. Emit the inverse `company --hosts--> facility`.

   GUARDED: only when facility and company both have a country and the two
   agree. `entity_resolution.compare()` already implements exactly this check
   (COUNTRY_GUARD), but it can only fire when both countries are known — and it
   is the unknown-country case that produced the one bad join in the file:

       facility:fei:3003603933  'Antibioticos de Mexico S.A. de C.V.'  (mx)
         --operated_by--> company:name:antibioticos-sa  'ANTIBIOTICOS SA'  (None)

   matched at 0.90 on the single shared token 'antibioticos'. The company node's
   own `country_evidence` reads "Spain is likely but unverified - do not assert
   it", so the guard never engaged and a Mexican plant was attached to a
   putatively Spanish DMF holder. Both Antibioticos de Mexico facilities are
   tagged AMOXICILLIN, so join 1 reconnects them on evidence that is actually
   true, without the identity claim.

   Refusing to join when a country is unknown is the same rule
   `ml/compliance.py` already applies to TAA: unproven is not the same as false.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import io_helpers as io  # noqa: E402

DATA = io.DATA_DIR
DRY = "--dry-run" in sys.argv

# Ingredient tag -> drug node. Deliberately not exhaustive; see the docstring.
INGREDIENT_TO_DRUG = {
    "AMOXICILLIN": "drug:amoxicillin",
    "AMPICILLIN": "drug:ampicillin",
}

SOURCE = "ml/signals/ (OASIS import refusals + FDA inspection classifications)"


def _read(name: str) -> list[dict]:
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else []


def main() -> int:
    signal_nodes = {n["id"]: n for n in _read("nodes.signals.json")}
    all_nodes = dict(signal_nodes)
    for f in ("nodes.openfda.json", "nodes.curated.json"):
        for n in _read(f):
            all_nodes.setdefault(n["id"], n)

    edges: list[dict] = []

    # --- join 1: ingredient tag -> drug -------------------------------------
    ingredient_joins = 0
    for nid, n in sorted(signal_nodes.items()):
        if n.get("type") != "facility":
            continue
        tags = {str(i).upper() for i in (n.get("attrs") or {}).get("ingredients") or []}
        for tag in sorted(tags & INGREDIENT_TO_DRUG.keys()):
            drug = INGREDIENT_TO_DRUG[tag]
            if drug not in all_nodes:
                print(f"  skip {nid}: {drug} is not a declared node")
                continue
            edges.append(io.edge(
                drug, nid, "produced_by", 3,
                citation=(
                    f"FDA records name this establishment (FEI "
                    f"{(n.get('attrs') or {}).get('fei')}) for {tag}. Source: {SOURCE}. "
                    f"Ingredient tag, not a production licence — the claim is that the "
                    f"facility appears in official records for this substance."
                ),
            ))
            ingredient_joins += 1

    # --- join 2: guarded inverse of operated_by -----------------------------
    inverse_joins, refused = 0, []
    for e in _read("edges.signals.json"):
        if e.get("rel") != "operated_by":
            continue
        fac, comp = all_nodes.get(e["src"]), all_nodes.get(e["dst"])
        if not fac or not comp:
            continue
        fc, cc = fac.get("country"), comp.get("country")
        if not fc or not cc or fc != cc:
            refused.append((e["src"], e["dst"], fc, cc))
            continue
        edges.append(io.edge(
            e["dst"], e["src"], "hosts", 3,
            citation=(
                f"Inverse of the operated_by edge in edges.signals.json, so the "
                f"facility is reachable in the direction the cascade walks. Identity "
                f"held by entity resolution AND both sides agree on country ({fc}). "
                f"Original: {e.get('citation', 'n/a')}"
            ),
        ))
        inverse_joins += 1

    print(f"ingredient -> drug joins : {ingredient_joins}")
    print(f"guarded inverse joins    : {inverse_joins}")
    if refused:
        print(f"\nREFUSED {len(refused)} operated_by inverse(s) — country unknown or mismatched:")
        for src, dst, fc, cc in refused:
            print(f"  {src} -> {dst}  (facility={fc!r} company={cc!r})")
        print("  These operated_by edges are still in edges.signals.json. An identity")
        print("  claim that cannot clear the country guard should not be load-bearing")
        print("  for beat 4 — see this file's docstring.")

    if DRY:
        print(f"\n--dry-run: {len(edges)} edge(s) not written")
        return 0

    total = io.write_edges(edges)
    print(f"\nwrote {len(edges)} edge(s); edges.curated.json now has {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
