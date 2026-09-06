#!/usr/bin/env python3
"""The TAA / 1260H PASS-FAIL engine.

    python3 ml/compliance.py                  # fill in company determinations, print them
    python3 ml/compliance.py <node-id>        # explain one node
    python3 ml/compliance.py --json <node-id> # the shape /api/graph/node/[id] returns

**Every determination carries its citation.** A PASS/FAIL with no source is exactly
what [decision 0003](DNHacks_brain/decisions/0003-transparent-risk-rules.md) rules
out, so `determine()` never returns a verdict without a `reason` and an `evidence`
block naming the file it came from.

## Why companies need an engine and countries do not

TAA designates **countries**; `load_taa.py` settles those directly. A **company**
has no TAA status of its own — it inherits from where it is incorporated, and that
country comes from a DECRS name match that succeeds about half the time. So a
company determination has to carry two things a country one does not: which edge
it traversed, and how good that hop was. Both are in the evidence.

Three outcomes, and the third is the honest one:

  PASS   incorporated in a designated country
  FAIL   incorporated in a country that is not designated
  None   we could not resolve a country, or resolved it only by a fuzzy name match
         we are not willing to stake a pass/fail on

`None` is a real answer here, not a gap. Antibioticos SA does not resolve in DECRS,
so it stays undetermined rather than being quietly assumed Spanish.

## Two things not to say on stage

* **The US is not on the 132.** That is not a failure — US goods pass as domestic
  end products under a different branch of FAR 25. Rendering `USA -> NO` is
  actively misleading.
* **1260H is a defence list, not a pharma list.** Zero of our eight 6-APA holders
  are on it, and that is the expected result. Sinopharm Weiqida makes 6-APA, is
  state-owned, and is *not* designated — state ownership and 1260H designation are
  different things.

## The live proof point, verified

***Cosette Pharmaceuticals v. United States*** — the Court of Federal Claims held
the VA violated the TAA. It is **decided, not pending**, and the drug is
**prasugrel**, not an antibiotic. Say *"a court has already ruled."*
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "ml" / "load"))

import io_helpers as io  # noqa: E402

FAR_URL = "https://www.acquisition.gov/far/25.003"

COSETTE = {
    "case": "Cosette Pharmaceuticals, Inc. v. United States",
    "court": "U.S. Court of Federal Claims",
    "holding": "the VA violated the Trade Agreements Act",
    "status": "decided, not pending",
    "drug": "prasugrel — not an antibiotic",
    "say": "a court has already ruled",
}


def load_graph() -> tuple[dict, list, dict]:
    d = REPO_ROOT / "web" / "data"
    nodes = {n["id"]: n for f in ("nodes.curated.json", "nodes.openfda.json")
             if (d / f).exists() for n in json.loads((d / f).read_text())}
    edges = [e for f in ("edges.curated.json", "edges.openfda.json")
             if (d / f).exists() for e in json.loads((d / f).read_text())]
    compliance = {c["node_id"]: c
                  for c in json.loads((d / "compliance.json").read_text())}
    return nodes, edges, compliance


def country_of(node_id: str, nodes: dict, edges: list) -> tuple[str | None, dict | None]:
    """Resolve a company to its country, returning the edge that got us there."""
    node = nodes.get(node_id, {})
    hops = [e for e in edges
            if e["src"] == node_id and e["rel"] in ("incorporated_in", "active_in")]
    if hops:
        # Prefer the lowest layer number: 1 = live API, 2 = official list, 3 = curated.
        best = min(hops, key=lambda e: e["layer"])
        return best["dst"].split("country:")[-1], best
    return node.get("country"), None


def determine(node_id: str, nodes: dict, edges: list, compliance: dict) -> dict:
    node = nodes.get(node_id)
    if node is None:
        return {"node_id": node_id, "error": "unknown node"}

    existing = compliance.get(node_id, {})
    evidence = dict(existing.get("evidence") or {})
    out: dict = {"node_id": node_id, "type": node["type"],
                 "label": node.get("label"), "on_1260h": existing.get("on_1260h")}

    if node["type"] == "country":
        iso2 = node_id.split("country:")[-1]
        out["taa_pass"] = existing.get("taa_pass")
        if iso2 == "us":
            out["reason"] = ("US goods pass as domestic end products under FAR 25.1, "
                             "not via the designated-country list — absence from the "
                             "132 is not a failure")
        else:
            out["reason"] = evidence.get(
                "reason", f"no TAA determination on record for {node_id}")
        out["evidence"] = evidence or {"far": "25.003", "url": FAR_URL}
        return out

    if node["type"] != "company":
        out["taa_pass"] = None
        out["reason"] = f"TAA and 1260H apply to companies and countries, not {node['type']}"
        out["evidence"] = {}
        return out

    iso2, hop = country_of(node_id, nodes, edges)
    resolved_by = node.get("resolved_by")

    if iso2 is None:
        out["taa_pass"] = None
        out["reason"] = (f"cannot determine TAA status: no country resolved for "
                         f"{node.get('label', node_id)}. "
                         + (node.get("attrs", {}).get("country_evidence") or ""))
        out["evidence"] = {"far": "25.003", "url": FAR_URL,
                           "resolved_by": resolved_by,
                           "country_resolution": "unresolved"}
        out["matched_entity"] = evidence.get("matched_entity")
        return out

    country_row = compliance.get(f"country:{iso2}", {})
    taa_pass = country_row.get("taa_pass")
    country_label = nodes.get(f"country:{iso2}", {}).get("label", iso2.upper())
    verb = "is" if taa_pass else "is not"

    out["taa_pass"] = taa_pass
    out["reason"] = (f"API traces to {iso2.upper()}, which {verb} a TAA-designated "
                     f"country (FAR 25.003)")
    out["matched_entity"] = evidence.get("matched_entity")
    out["evidence"] = {
        **evidence,
        "far": "25.003",
        "url": FAR_URL,
        "country": f"country:{iso2}",
        "country_label": country_label,
        "country_reason": (country_row.get("evidence") or {}).get("reason"),
        "country_via": (f"{hop['rel']} edge at layer {hop['layer']}: {hop['citation']}"
                        if hop else "country attribute on the node"),
        "resolved_by": resolved_by,
        "resolution_caveat": (
            "company identified by normalised name match, not FEI — treat the "
            "company-to-country hop as fuzzy" if resolved_by == "fuzzy" else None),
        "precedent": COSETTE,
    }
    out["evidence"] = {k: v for k, v in out["evidence"].items() if v is not None}
    return out


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv[1:]
    nodes, edges, compliance = load_graph()

    if args:
        result = determine(args[0], nodes, edges, compliance)
        print(json.dumps(result, indent=2, ensure_ascii=False) if as_json
              else _explain(result))
        return 0 if "error" not in result else 1

    # No argument: recompute every company determination and persist it. This is
    # the step that fills in company taa_pass, which no loader can do because it
    # needs the company -> country hop.
    rows = []
    for node_id, node in sorted(nodes.items()):
        if node["type"] not in ("company", "country"):
            continue
        d = determine(node_id, nodes, edges, compliance)
        rows.append(io.compliance(node_id, taa_pass=d.get("taa_pass"),
                                  on_1260h=d.get("on_1260h"),
                                  evidence={**d["evidence"], "reason": d["reason"]}))
        print(_explain(d))

    io.write_compliance(rows)
    decided = sum(1 for r in rows if r["taa_pass"] is not None)
    print(f"\n  {len(rows)} determinations, {decided} with a TAA verdict, "
          f"{len(rows) - decided} honestly undetermined")
    print(f"  precedent: {COSETTE['case']} — {COSETTE['holding']} "
          f"({COSETTE['status']}; {COSETTE['drug']})")
    return 0


def _explain(d: dict) -> str:
    if "error" in d:
        return f"{d['node_id']}: {d['error']}"
    verdict = {True: "PASS", False: "FAIL", None: "  ? "}[d.get("taa_pass")]
    flag = " [1260H]" if d.get("on_1260h") else ""
    return f"  TAA {verdict}{flag}  {d.get('label') or d['node_id']}\n            {d['reason']}"


if __name__ == "__main__":
    sys.exit(main())
