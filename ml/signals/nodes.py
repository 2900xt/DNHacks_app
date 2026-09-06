"""Facility nodes for the signals, and the company<->facility bridge.

Why this exists: every FEI signal lands on `facility:fei:<n>`, and until Nikhil's
Sat 21:45 fix nothing was creating that half of the id space — signals attached
to nothing and a red node rendered green with its evidence sitting beside it,
unattached and silent. He now emits facility nodes for the two anchors he knows
about. The rest are mine, because my loaders are what carry the firm names.

    python3 -m ml.signals.nodes    # -> web/data/{nodes,edges}.signals.json

Two files, both mine. I do not write to anyone else's.

--------------------------------------------------------------------------------
Scope — deliberately NOT every facility
--------------------------------------------------------------------------------
2,034 FEIs have signals. Emitting all of them would add ~2,000 orphan nodes with
no edges, which is clutter, not a graph. We emit a facility node only when it
can actually connect to something:

Scope is enforced in the OASIS loader instead: refusals are kept only for
chokepoint countries (CN/IN) or tracked ingredients. Everything that survives
that gets a node here, so no signal references a node that does not exist.

--------------------------------------------------------------------------------
The bridge, and why it refuses more than it accepts
--------------------------------------------------------------------------------
Yash's 6-APA producers are `company:name:*` (fuzzy, from the DMF list). My
evidence is `facility:fei:*` (exact). Linking them is exactly the job entity
resolution exists for — and exactly where it is most dangerous:

    UNITED LABORATORIES CHENGDU          -> both score 1.00 against
    THE UNITED LABORATORIES INNER MONGOLIA   facility:fei:3006531950
                                             = Zhuhai United Laboratories

Three different plants, one token core `{united}`. That is benchmark FP #17
firing on live graph data, and picking the argmax would hang one plant's
inspection history on another. `resolve()` refuses on a tie instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from entity_resolution import resolve  # noqa: E402

from .common import REPO, Signal  # noqa: E402

DATA = REPO / "web" / "data"
NODES_OUT = DATA / "nodes.signals.json"
EDGES_OUT = DATA / "edges.signals.json"

ANCHORS = {"3004446312", "3004497364", "3003196232", "3002807977"}


def _load(name: str) -> list:
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else []


def build() -> tuple[list[dict], list[dict]]:
    signals = _load("signals.json")
    curated = _load("nodes.curated.json")

    # Curated company nodes are the bridge targets.
    companies = {n["id"]: (n.get("label") or n["id"].split(":")[-1].replace("-", " "))
                 for n in curated if n["id"].startswith("company:")}
    company_countries = {n["id"]: n.get("country") for n in curated if n["id"].startswith("company:")}

    # Collect one facility profile per FEI.
    facilities: dict[str, dict] = {}
    for s in signals:
        nid = s["node_id"]
        if not nid.startswith("facility:fei:"):
            continue
        fei = nid.rsplit(":", 1)[1]
        p = s.get("payload") or {}
        f = facilities.setdefault(fei, {"fei": fei, "names": set(), "country": None,
                                        "city": None, "n": 0, "ingredients": set()})
        f["n"] += 1
        if p.get("firm"):
            f["names"].add(p["firm"])
        f["country"] = f["country"] or p.get("country")
        f["city"] = f["city"] or p.get("city")
        if p.get("ingredient"):
            f["ingredients"].add(p["ingredient"])

    nodes, edges, refusals = [], [], []
    for fei, f in sorted(facilities.items()):
        if not f["names"]:
            continue
        name = sorted(f["names"], key=len)[-1]        # longest = most qualified
        country = (f["country"] or "")[:2].lower() or None

        match, why = resolve(name, companies, country=f["country"], countries=company_countries)
        # Record the refusal BEFORE the keep filter. The most interesting
        # ambiguity (Zhuhai vs the two United Labs sites) is on a facility we
        # would otherwise drop, so filtering first made it invisible.
        if "AMBIGUOUS" in why:
            refusals.append((fei, name, why))
        # Declare a node for every facility we reference. The scope filter now
        # lives in the OASIS loader (chokepoint countries + tracked ingredients),
        # so anything reaching here is in scope by construction - and a signal
        # referencing an undeclared node is dead weight that the validator is
        # right to warn about.

        nodes.append({
            "id": f"facility:fei:{fei}",
            "type": "facility",
            "label": name,
            **({"country": country} if country else {}),
            "resolved_by": "fei",
            "attrs": {"fei": fei, "city": f["city"], "signal_count": f["n"],
                      "ingredients": sorted(f["ingredients"]),
                      "name_variants": sorted(f["names"])},
        })
        if match:
            edges.append({
                "src": f"facility:fei:{fei}", "dst": match, "rel": "operated_by",
                "layer": 2,
                "citation": f"entity resolution, {why} (ml/entity_resolution.py)",
            })

    # Company nodes referenced by Federal Register signals. These are 1260H
    # designations read out of the notice's full text; nobody else declares them.
    # Per the contract a `company:name:` id MUST be resolved_by 'fuzzy' - it is a
    # normalized name, not an identifier, and the UI has to be able to mark it.
    declared = {n["id"] for n in nodes}
    referenced = {s["node_id"] for s in signals if s["node_id"].startswith("company:name:")}
    for cid in sorted(referenced - declared):
        srcs = {s["source"] for s in signals if s["node_id"] == cid}
        nodes.append({
            "id": cid,
            "type": "company",
            "label": cid.rsplit(":", 1)[1].replace("-", " ").title(),
            "resolved_by": "fuzzy",
            "attrs": {"note": "named in a Federal Register 1260H designation; "
                              "country deliberately not asserted - the list designates "
                              "Chinese military companies but some entities are "
                              "incorporated elsewhere",
                      "sources": sorted(srcs)},
        })

    return nodes, edges, refusals


def main() -> int:
    nodes, edges, refusals = build()
    NODES_OUT.write_text(json.dumps(nodes, indent=2) + "\n")
    EDGES_OUT.write_text(json.dumps(edges, indent=2) + "\n")
    print(f"wrote {len(nodes)} facility nodes -> {NODES_OUT.name}")
    print(f"wrote {len(edges)} operated_by edges -> {EDGES_OUT.name}")
    if refusals:
        print(f"\n{len(refusals)} bridge(s) REFUSED as ambiguous — this is correct behaviour:")
        for fei, name, why in refusals:
            print(f"  {fei}  {name[:40]:40s} {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
