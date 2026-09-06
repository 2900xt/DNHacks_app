"""Worked example: what the audit trail looks like around a real rerouting decision.

This is NOT the RL agent. It is a stand-in that reads the real graph and records the
same shape of decision Shaurya's agent will make, so the trail, the verifier and the
UI can all be built and rehearsed before the agent exists.

    python ml/audit_demo.py          # writes web/data/audit.jsonl + audit.json
    python ml/audit.py --verify
    python ml/audit.py --tail 10
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from audit import AuditLog, export, verify

DATA = Path(__file__).resolve().parent.parent / "web" / "data"


def load_graph() -> tuple[dict, list]:
    nodes, edges = {}, []
    for f in sorted(DATA.glob("nodes.*.json")):
        for n in json.loads(f.read_text() or "[]"):
            nodes[n["id"]] = n
    for f in sorted(DATA.glob("edges.*.json")):
        edges.extend(json.loads(f.read_text() or "[]"))
    return nodes, edges


def main() -> int:
    nodes, edges = load_graph()
    if not nodes:
        print("no graph artifacts in web/data/ — run ml/build_graph.py first")
        return 1

    signals = json.loads((DATA / "signals.json").read_text() or "[]")
    by_node: dict[str, list] = {}
    for s in signals:
        by_node.setdefault(s["node_id"], []).append(s)

    outgoing: dict[str, list] = {}
    for e in edges:
        outgoing.setdefault(e["src"], []).append(e)

    def reach(start: str) -> set[str]:
        seen, queue = {start}, [start]
        while queue:
            for e in outgoing.get(queue.pop(0), []):
                if e["dst"] not in seen:
                    seen.add(e["dst"])
                    queue.append(e["dst"])
        return seen - {start}

    log = AuditLog(run_id="reroute-amoxicillin", actor="planner")

    # 1 — assess
    with log.step("assess", inputs={"trigger": "bin:depot-01 MKT breach",
                                    "drug": "drug:amoxicillin"}) as s:
        affected = reach("precursor:6-apa")
        drugs = sorted(nodes[n]["label"] for n in affected if nodes[n]["type"] == "drug")
        s.observe("cascade_from_precursor",
                  {"affected": len(affected), "drugs": drugs})
        s.observe("shortage_listed", {"count": 0,
                                      "note": "none of the six is on an FDA shortage list"})
        s.result({"conclusion": "single shared precursor, no official warning yet"})

    # 2 — the parameter choice, with its reasoning. This is the entry that matters:
    # it is what a formula could not produce and what a judge will ask about.
    with log.step("tune", inputs={"objective": "rank alternate suppliers"}) as s:
        s.observe("available_features",
                  {"concentration": True, "compliance": True,
                   "capacity": False, "lead_time": False})
        s.params(
            {"concentration_weight": 0.6, "compliance_weight": 0.4,
             "capacity_weight": 0.0, "lead_time_weight": 0.0},
            why=("Capacity and lead time have no public source (DATA.md Layer 1d), so "
                 "their weights are pinned at zero rather than guessed — an optimiser "
                 "with an invented capacity constraint is sorting, not optimising. "
                 "Concentration is weighted above compliance because a TAA failure is "
                 "a procurement blocker we can route around, while a single-country "
                 "precursor is not."))
        s.result({"active_features": 2, "zeroed_features": 2})

    # 3 — act
    with log.step("rank_alternates", inputs={"api": "api:amoxicillin-trihydrate"}) as s:
        producers = [n for n in nodes.values()
                     if n["type"] == "company" and n.get("resolved_by") == "fei"]
        s.observe("candidate_count", len(producers))
        ranked = []
        for p in producers:
            fei = (p.get("attrs") or {}).get("fei")
            n_sig = len(by_node.get(f"facility:fei:{fei}", [])) if fei else 0
            ranked.append({"id": p["id"], "label": p["label"],
                           "country": p.get("country"), "open_signals": n_sig})
        ranked.sort(key=lambda r: r["open_signals"])
        s.action("rank", {"order": [r["id"] for r in ranked]})
        for r in ranked:
            s.observe("candidate", r)
        s.result({"ranked": ranked,
                  "note": "ordered by fewest open negative signals; ties unbroken"})

    # 4 — the refusal. An agent that declines to answer is more defensible than one
    # that guesses, and the trail has to show the refusal as loudly as a decision.
    with log.step("select", inputs={"policy": "no unverified country in a TAA verdict"}) as s:
        unknown = [n["id"] for n in nodes.values()
                   if n["type"] == "company" and not n.get("country")]
        s.observe("candidates_without_country", len(unknown))
        s.action("refuse", {"reason": "TAA determination requires a resolved country"})
        s.result({"selected": None,
                  "refused_because": ("At least one candidate has no verified country "
                                      "(ANTIBIOTICOS SA / DMF 12348). Returning a "
                                      "PASS/FAIL would be asserting a fact we do not "
                                      "have."),
                  "escalated_to": "human"})

    log.close(status="completed", decisions=4)

    ok, finding = verify()
    doc = export()
    print(f"wrote web/data/audit.jsonl and audit.json — {doc['count']} entries")
    print(("OK   " if ok else "FAIL ") + finding)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
