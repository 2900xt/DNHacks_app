"""Build the amoxicillin subgraph from openFDA -> web/data/*.openfda.json

This is the spine of the demo. It emits Layer 1 (live API) nodes and edges only.
Yash's loaders emit Layer 2 (official lists) and Layer 3 (curated precursor edges)
into their own files; the app merges them. Never write to a file you do not own.

Run:
    python ml/build_graph.py
    python ml/build_graph.py --refresh    # re-hit openFDA instead of the cache
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from openfda import ndc

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "web" / "data"
NODES_OUT = OUT_DIR / "nodes.openfda.json"
EDGES_OUT = OUT_DIR / "edges.openfda.json"

# ---------------------------------------------------------------------------
# ⚠️ SHARED CONTRACT — these ids must match Yash's `precursor:6-apa --feeds--> api:*`
# edges character-for-character or the fan-out silently breaks. If he uses different
# strings, change them HERE and nowhere else.
# ---------------------------------------------------------------------------

# The six drugs the brain traces to 6-APA. `api_id` follows the example form in
# team/briefs/README.md ("the active ingredient as shipped"). One API node per drug;
# observed salt variants get recorded in the node's attrs rather than forking the id.
SIX_APA_DRUGS: list[dict[str, str]] = [
    {"drug": "amoxicillin",   "api_id": "api:amoxicillin-trihydrate", "api_label": "Amoxicillin trihydrate"},
    {"drug": "ampicillin",    "api_id": "api:ampicillin",             "api_label": "Ampicillin"},
    {"drug": "piperacillin",  "api_id": "api:piperacillin",           "api_label": "Piperacillin"},
    {"drug": "dicloxacillin", "api_id": "api:dicloxacillin-sodium",   "api_label": "Dicloxacillin sodium"},
    {"drug": "nafcillin",     "api_id": "api:nafcillin-sodium",       "api_label": "Nafcillin sodium"},
    {"drug": "oxacillin",     "api_id": "api:oxacillin-sodium",       "api_label": "Oxacillin sodium"},
]

# EO 13944 essential-medicines status. Per Yash's correction: 4 penicillins are on the
# list, but only 3 of the 6 we trace to 6-APA. Penicillin G is a 7th derivative and is
# deliberately not a node here. Say both numbers on stage; do not round up.
ON_EO_13944 = {"amoxicillin", "ampicillin", "piperacillin"}

# FEI is the exact join key (100% populated on inspection rows). openFDA does NOT carry
# FEI, so these come from the brain's verified facility research. A labeler that appears
# here resolves exactly; everything else falls back to a fuzzy name id.
#   Aurobindo:  FEI 3004446312, OAI 09/05/2025 -- the hero node.
#   Centrient:  FEI 3004497364, OAI 01/27/2026 -- the amoxicillin precursor maker.
#               NOT 3002807979 -- that is Sun Pharmaceutical, Mohali. The two Sun Pharma
#               FEIs (…977 Dewas, …979 Mohali) sit one digit apart and nowhere near
#               Centrient's. Caught by Parth Sat 21:34, verified against signals.json.
# Source: project/datasets/fda-inspection-classification.md, briefs/README.md
KNOWN_FEI: dict[str, dict[str, str]] = {
    "aurobindo pharma limited": {"fei": "3004446312", "country": "IN", "label": "Aurobindo Pharma Limited"},
    "centrient pharmaceuticals india private limited": {"fei": "3004497364", "country": "IN", "label": "Centrient Pharmaceuticals India Private Limited"},
}

COUNTRY_LABELS = {"in": "India", "cn": "China", "us": "United States"}

CITE_OPENFDA = "openFDA /drug/ndc.json"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def slug(text: str) -> str:
    """Lowercase, non-alphanumerics collapsed to single hyphens. Per the id rules in
    briefs/README.md. Nothing else is dropped."""
    out, prev_hyphen = [], False
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
            prev_hyphen = False
        elif not prev_hyphen:
            out.append("-")
            prev_hyphen = True
    return "".join(out).strip("-")


def ingredient_words(product: dict) -> set[str]:
    """Whole words from every active ingredient name.

    Whole-word, never substring: `OXACILLIN` is a substring of `DICLOXACILLIN` and
    substring-matching silently merges two different drugs. See the OXACILLIN trap in
    project/datasets/README.md.
    """
    words: set[str] = set()
    for ing in product.get("active_ingredients") or []:
        for word in (ing.get("name") or "").lower().replace(",", " ").split():
            words.add(word.strip("()"))
    return words


class GraphBuilder:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str, str], dict] = {}

    def node(self, node_id: str, node_type: str, label: str, **kw) -> str:
        existing = self.nodes.get(node_id)
        if existing:
            # Merge attrs rather than clobbering, and never let a later None overwrite
            # a value we already have. openFDA ships duplicate rows for one product_ndc
            # (same NDC, different spl_id) where only one carries application_number --
            # see DUP_NDC_NOTE below.
            attrs = existing.setdefault("attrs", {})
            for key, value in (kw.get("attrs") or {}).items():
                if value is not None or key not in attrs:
                    attrs[key] = value
            existing["_rows"] = existing.get("_rows", 1) + 1
            return node_id
        kw.setdefault("attrs", {})
        self.nodes[node_id] = {
            "id": node_id,
            "type": node_type,
            "label": label,
            "country": kw.get("country"),
            "critical": kw.get("critical", False),
            "attrs": kw.get("attrs") or {},
            "resolved_by": kw.get("resolved_by"),
            "_rows": 1,
        }
        return node_id

    def edge(self, src: str, dst: str, rel: str, *, layer: int, citation: str) -> None:
        # Layer 3 requires a citation -- no citation, no edge. Everything here is
        # layer 1, but the guard stays so the rule cannot rot.
        if layer == 3 and not citation:
            raise ValueError(f"layer 3 edge without citation: {src} -{rel}-> {dst}")
        self.edges[(src, dst, rel)] = {
            "src": src, "dst": dst, "rel": rel, "layer": layer, "citation": citation,
        }

    def company(self, labeler_name: str) -> str:
        """FEI wins. Fall back to a normalized name id and mark it fuzzy so the UI
        can flag it."""
        known = KNOWN_FEI.get(labeler_name.strip().lower())
        if known:
            # `country` is ISO-2 LOWERCASED per web/app/lib/types.ts -- the display name
            # goes in the country node's label, not in this field.
            iso2 = known["country"].lower()
            node_id = f"company:fei:{known['fei']}"
            self.node(node_id, "company", known["label"], country=iso2,
                      resolved_by="fei", attrs={"fei": known["fei"], "labeler_name": labeler_name})
            country_id = self.node(f"country:{iso2}", "country", COUNTRY_LABELS.get(iso2, iso2.upper()),
                                   country=iso2)
            self.edge(node_id, country_id, "incorporated_in", layer=1, citation="FDA FEI registration")

            # 🔴 THE SEAM. Parth's signals attach to `facility:fei:*` (an inspection is of
            # a SITE), but openFDA gives us labelers, which are companies. Without a
            # facility node and this edge, `facility:fei:3004446312` in signals.json has
            # nothing to land on and the hero node renders green with an OAI sitting
            # right next to it. Both id forms are legal per briefs/README.md; nobody was
            # creating the facility half. Same FEI, so the join is exact -- no fuzzy hop.
            facility_id = self.node(f"facility:fei:{known['fei']}", "facility",
                                    f"{known['label']} (site)", country=iso2,
                                    resolved_by="fei", attrs={"fei": known["fei"]})
            self.edge(facility_id, node_id, "operated_by", layer=1,
                      citation="FDA FEI registration")
            self.edge(facility_id, country_id, "located_in", layer=1,
                      citation="FDA FEI registration")
            return node_id

        node_id = f"company:name:{slug(labeler_name)}"
        self.node(node_id, "company", labeler_name, resolved_by="fuzzy",
                  attrs={"labeler_name": labeler_name})
        return node_id


def build(refresh: bool = False) -> tuple[GraphBuilder, dict]:
    g = GraphBuilder()
    stats: dict[str, Any] = {"products_by_drug": {}, "skipped_no_ingredient_match": 0}

    for entry in SIX_APA_DRUGS:
        drug, api_id = entry["drug"], entry["api_id"]

        drug_id = g.node(f"drug:{drug}", "drug", drug.capitalize(),
                         critical=drug in ON_EO_13944,
                         attrs={"eo_13944": drug in ON_EO_13944})
        g.node(api_id, "api", entry["api_label"], attrs={"salt_forms": []})
        # The API is what the finished drug is made of; this is the hop the precursor
        # layer hangs off (Yash: precursor:6-apa --feeds--> api:*).
        g.edge(api_id, drug_id, "active_in", layer=1, citation=CITE_OPENFDA)

        # NOTE: openFDA search terms are separated by spaces here, NOT the "+AND+" form
        # you see in curl examples -- requests percent-encodes the "+" and the query
        # silently returns 0 results.
        products = ndc(f'generic_name:"{drug}"', limit=1000, refresh=refresh)

        kept = 0
        for product in products:
            # Trust the ingredient list, not the generic_name string. This is what
            # correctly keeps "amoxicillin and clavulanate potassium" (a real
            # amoxicillin product) while never confusing oxacillin with dicloxacillin.
            if drug not in ingredient_words(product):
                stats["skipped_no_ingredient_match"] += 1
                continue

            product_ndc = product.get("product_ndc")
            labeler = (product.get("labeler_name") or "").strip()
            if not product_ndc or not labeler:
                continue

            salts = {(i.get("name") or "").title() for i in product.get("active_ingredients") or []}
            g.nodes[api_id]["attrs"]["salt_forms"] = sorted(
                set(g.nodes[api_id]["attrs"]["salt_forms"]) | {s for s in salts if drug in s.lower()}
            )

            product_id = g.node(
                f"product:ndc:{product_ndc}", "product",
                product.get("brand_name") or product.get("generic_name") or product_ndc,
                attrs={
                    "product_ndc": product_ndc,
                    "generic_name": product.get("generic_name"),
                    "labeler_name": labeler,
                    "dosage_form": product.get("dosage_form"),
                    "route": product.get("route"),
                    "application_number": product.get("application_number"),
                    "marketing_category": product.get("marketing_category"),
                    "rxcui": (product.get("openfda") or {}).get("rxcui"),
                },
            )

            g.edge(product_id, api_id, "formulated_from", layer=1, citation=CITE_OPENFDA)
            g.edge(product_id, drug_id, "instance_of", layer=1, citation=CITE_OPENFDA)

            company_id = g.company(labeler)
            g.edge(company_id, product_id, "markets", layer=1, citation=CITE_OPENFDA)
            g.edge(company_id, api_id, "produced_by", layer=1, citation=CITE_OPENFDA)
            kept += 1

        stats["products_by_drug"][drug] = kept
        print(f"  {drug:15} {kept:4} products  ({len(products)} returned, "
              f"{len(products) - kept} filtered out)")

    return g, stats


def _row_count(node: dict) -> int:
    """How many openFDA rows collapsed into this node. Lives in `_rows` while building,
    moves into attrs on write, so read whichever is present."""
    return node.get("_rows") or node.get("attrs", {}).get("openfda_rows", 1)


def verify(g: GraphBuilder) -> bool:
    """§3 of the brief. If this fails, nothing downstream works."""
    ok = True
    print("\nverify")

    # 1. The hero node and its amoxicillin products.
    #
    # ⚠️ DUP_NDC_NOTE -- the brain says "26 amoxicillin NDCs" (briefs/README.md,
    # briefs/nikhil.md). Measured live: openFDA returns 26 ROWS but only 19 DISTINCT
    # product_ndc values. Seven NDCs appear twice -- same product_ndc, different
    # spl_id, one copy carrying application_number and one not. So the honest stage
    # line is "19 products, 26 openFDA listings", not "26 products".
    hero = "company:fei:3004446312"
    hero_products = [e for e in g.edges.values() if e["src"] == hero and e["rel"] == "markets"]
    hero_amox = [e for e in hero_products
                 if (g.nodes[e["dst"]]["attrs"].get("generic_name") or "").lower().startswith("amoxicillin")]
    rows = sum(_row_count(g.nodes[e["dst"]]) for e in hero_amox)
    status = "OK " if len(hero_amox) == 19 and rows == 26 else "FAIL"
    if not (len(hero_amox) == 19 and rows == 26):
        ok = False
    print(f"  {status} Aurobindo (FEI 3004446312) -> {len(hero_amox)} distinct amoxicillin NDCs "
          f"from {rows} openFDA rows (expected 19 / 26)")
    if g.nodes.get(hero, {}).get("resolved_by") != "fei":
        print("  FAIL hero node is not FEI-resolved")
        ok = False

    # 2. The fan-out: walk 6-APA -> amoxicillin, then back out to the five siblings.
    # Yash's layer-3 edge is not in this file, so we simulate it: every api: node is
    # what 6-APA feeds.
    api_nodes = sorted(n for n in g.nodes if n.startswith("api:"))
    reached = set()
    for e in g.edges.values():
        if e["rel"] == "active_in" and e["src"] in api_nodes:
            reached.add(e["dst"])
    status = "OK " if len(reached) == 6 else "FAIL"
    if len(reached) != 6:
        ok = False
    print(f"  {status} 6-APA -> {len(api_nodes)} API nodes -> {len(reached)} drugs (expected 6)")
    print(f"       fan-out: {', '.join(sorted(n.split(':')[1] for n in reached))}")

    # 3. The seam: every signal node this graph is supposed to carry must actually exist
    # as a node. Reads Parth's signals.json if it has landed; skips quietly if not.
    signals_file = OUT_DIR / "signals.json"
    if signals_file.exists():
        signals = json.loads(signals_file.read_text() or "[]")
        # `mine` = this facility has openFDA products under it, so the node is ours to
        # emit. Sun Pharma Dewas is not an amoxicillin labeler in openFDA at all (its
        # refusals are on imported API, not finished product), so it has no product chain
        # here and its node belongs to whoever owns the signal source. Flagged, not faked.
        anchors = {"facility:fei:3004446312": ("Aurobindo", True),
                   "facility:fei:3004497364": ("Centrient", True),
                   "facility:fei:3002807977": ("Sun Pharma Dewas", False)}
        for node_id, (name, mine) in sorted(anchors.items(), key=lambda kv: kv[1][0]):
            n_sig = sum(1 for s in signals if s.get("node_id") == node_id)
            present = node_id in g.nodes
            if present:
                status, note = "OK ", "node exists"
            elif mine:
                status, note, ok = "FAIL", "MISSING -- signal has nothing to land on", False
            else:
                status = "⚠️ "
                note = "no node -- not ours (no openFDA product chain); needs an owner"
            print(f"  {status} {name:18} {n_sig} signals -> {note}")
        orphans = {s["node_id"] for s in signals} - set(g.nodes)
        print(f"  -- {len(orphans)} signal node_ids not in this file "
              f"(Yash's + Parth's own to create)")

    # 4. Every company:name: id must be marked fuzzy.
    bad = [n for n, v in g.nodes.items() if n.startswith("company:name:") and v["resolved_by"] != "fuzzy"]
    status = "OK " if not bad else "FAIL"
    if bad:
        ok = False
    print(f"  {status} all company:name: ids marked resolved_by='fuzzy' ({len(bad)} violations)")

    return ok


def main() -> int:
    refresh = "--refresh" in sys.argv
    print(f"building amoxicillin subgraph{' (--refresh: re-hitting openFDA)' if refresh else ''}\n")

    g, stats = build(refresh=refresh)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    nodes = sorted(g.nodes.values(), key=lambda n: (n["type"], n["id"]))
    for n in nodes:
        n["attrs"]["openfda_rows"] = n.pop("_rows", 1)
    edges = sorted(g.edges.values(), key=lambda e: (e["layer"], e["rel"], e["src"], e["dst"]))
    NODES_OUT.write_text(json.dumps(nodes, indent=2))
    EDGES_OUT.write_text(json.dumps(edges, indent=2))

    by_type: dict[str, int] = defaultdict(int)
    for n in nodes:
        by_type[n["type"]] += 1
    fuzzy = sum(1 for n in nodes if n["resolved_by"] == "fuzzy")

    print(f"\nwrote {NODES_OUT.relative_to(REPO_ROOT)}  {len(nodes)} nodes")
    for t, c in sorted(by_type.items()):
        print(f"       {t:9} {c}")
    print(f"wrote {EDGES_OUT.relative_to(REPO_ROOT)}  {len(edges)} edges")
    print(f"\nresolution: {len(nodes) - fuzzy} exact, {fuzzy} fuzzy "
          f"({fuzzy / max(by_type['company'], 1):.0%} of companies)")

    return 0 if verify(g) else 1


if __name__ == "__main__":
    sys.exit(main())
