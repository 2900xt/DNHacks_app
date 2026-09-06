"""AEGIS — the pathfinder: when a supplier goes down, who else can make this?

    python3 ml/aegis.py --facility 3004497364     # Centrient India goes down
    python3 ml/aegis.py --substance "amoxicillin trihydrate"
    python3 ml/aegis.py --demo                    # the 6-APA cascade

--------------------------------------------------------------------------------
This is a RANKED SHORTLIST, not an optimiser. The distinction is the whole point.
--------------------------------------------------------------------------------

`../DNHacks_brain/project/DATA.md` is blunt about why:

> ❌ **Capacity and lead time have no public source at all.** An optimizer without
> a capacity constraint is a sort, not an optimization.

That is correct and this file does not pretend otherwise. What IS public, and what
this ranks on:

  * **Capability** — who holds an active Type II DMF for the same substance.
    SUBJECT and HOLDER sit in the same row, so this hop needs no fuzzy matching.
  * **Registration** — is that holder a DECRS establishment flagged
    `API MANUFACTURE`, i.e. legally able to supply the US market.
  * **Geography** — does re-routing there actually diversify, or land you in the
    same country as the failure you are routing around.
  * **Procurement eligibility** — TAA-designated country, so a VA or DoD buyer can
    legally buy it (China and India are not designated).
  * **The alternate's own risk** — does the candidate have its own OAI or cGMP
    refusal history? Routing out of one fire into another is the failure mode
    that matters here, and we have the signals to check it.

What it CANNOT tell you, stated on every output rather than buried:
  ❌ capacity — nobody publishes what a plant can make
  ❌ lead time — same
  ❌ whether they would actually sell to you
  ❌ whether they are already at their limit supplying someone else

So the output is "here are the firms with the paperwork to make this, ranked by
how much re-routing there would actually help" — a procurement shortlist, which
is a real deliverable, rather than a solved allocation problem, which would be
a lie.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.entity_resolution import core_tokens, normalize  # noqa: E402
from ml.xlsx import rows as xlsx_rows  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CACHE = REPO / "data" / "cache"
DECRS_URL = "https://www.accessdata.fda.gov/cder/drls_reg.zip"
DECRS_ZIP = CACHE / "decrs" / "drls_reg.zip"
DMF_URL = "https://www.fda.gov/media/192069/download?attachment"
DMF_XLSX = CACHE / "dmf" / "dmf.xlsx"
UA = "Mozilla/5.0 (CHOKEPOINT/DNHacks research)"


def fetch(url: str, dest: Path, timeout: int = 180) -> Path:
    """curl, not urllib - this python's framework install trusts no CA roots.

    accessdata.fda.gov also serves an abuse-detection page to a bare user agent,
    so the browser UA is required, not cosmetic.
    """
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["curl", "-sSL", "--fail", "-A", UA, "--max-time",
                        str(timeout), url, "-o", str(dest)], capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"fetch failed: {url}\n{r.stderr.decode(errors='replace')[:300]}")
    return dest

#: China and India are NOT TAA-designated. Full list is 132 countries via FAR
#: 25.003 (Yash's ml/load/load_taa.py). We carry the ISO3 codes our graph reaches
#: plus the major API-producing designated countries, and mark anything unknown
#: as unverified rather than guessing PASS.
TAA_DESIGNATED_ISO3 = {
    "AUT", "BEL", "BGR", "CAN", "HRV", "CYP", "CZE", "DNK", "EST", "FIN", "FRA",
    "DEU", "GRC", "HUN", "IRL", "ITA", "LVA", "LTU", "LUX", "MLT", "NLD", "POL",
    "PRT", "ROU", "SVK", "SVN", "ESP", "SWE", "GBR", "CHE", "NOR", "ISL", "JPN",
    "KOR", "SGP", "AUS", "NZL", "ISR", "MEX", "CHL", "PER", "COL", "PAN", "DOM",
    "CRI", "GTM", "HND", "NIC", "SLV", "MAR", "BHR", "OMN", "TWN", "HKG", "USA",
}
NOT_DESIGNATED = {"CHN", "IND", "RUS", "BRA", "ARG", "THA", "VNM", "IDN", "MYS"}

CHOKEPOINT_ISO3 = {"CHN", "IND"}


def _tokens(v: str) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", (v or "").lower()).split()


def same_substance(query: str, candidate: str) -> bool:
    """Is `candidate` a spelling of the substance `query`?

    Two traps, and they pull in opposite directions - Yash's load_dmf.py states
    the rule exactly: *use squash for spelling variants of one molecule; use
    boundaries for one name inside another. They are not interchangeable.*

    SQUASH ALONE OVER-MATCHES. `oxacillin` is a substring of `CLOXACILLIN`,
    `DICLOXACILLIN` and `FLUCLOXACILLIN`, so squash-substring matching returned
    cloxacillin holders as oxacillin alternates - a buyer routed to a firm that
    does not make the molecule at all. A one-character subject spelled `L` also
    matched every query, because "l" is a substring of nearly anything.

    BOUNDARIES ALONE UNDER-MATCH. 6-APA is spelled `6-AMINOPENICILLANIC ACID`
    and `6-AMINO PENICILLANIC ACID` - the split falls *inside* a word, so no
    token boundary can bridge them.

    So: accept on a whole-token match, OR on squash equality/prefix (which covers
    intra-word punctuation), and nothing else.
    """
    q, c = _tokens(query), _tokens(candidate)
    if not q or not c:
        return False
    qs, cs = squash(query), squash(candidate)
    if len(qs) < 4 or len(cs) < 4:
        return False
    # whole-token containment, in either direction
    if all(t in c for t in q) or all(t in q for t in c):
        return True
    # intra-word punctuation variants of one molecule
    return qs == cs or cs.startswith(qs) or qs.startswith(cs)


def squash(v: str) -> str:
    """Collapse a substance name to letters+digits only.

    The register spells one molecule many ways. 6-APA alone appears as
    `6-AMINOPENICILLANIC ACID`, `6-AMINO PENICILLANIC ACID`, `6-APA`,
    `6-AMINO-PENICILLANIC ACID (6-APA) BULK DRUG SUBSTANCE` and eight more.
    Keying on the normalised string splits one molecule across twelve buckets and
    reports 6 alternate suppliers where there are 27 - a four-fold understatement,
    and in the wrong direction, because it makes a chokepoint look tighter than it
    is. Squashing finds them; this is the same trick load_dmf.py uses.
    """
    return re.sub(r"[^a-z0-9]", "", (v or "").lower())


def dmf_holders(substance: str) -> tuple[dict[str, set[str]], list[str]]:
    """Holders of a DMF for `substance`, split active vs inactive.

    Returns ({"active": {...}, "inactive": {...}}, matched_spellings).
    An inactive DMF is not a supplier you can call - it is a firm that once filed.
    Reporting them together would inflate the shortlist with Hoechst and Beecham.
    """
    fetch(DMF_URL, DMF_XLSX)
    it = xlsx_rows(DMF_XLSX)
    next(it)
    out = {"active": set(), "inactive": set()}
    spellings: set[str] = set()
    for r in it:
        if len(r) < 6 or r[2] != "II" or not (r[4] and r[5]):
            continue
        if not same_substance(substance, r[5]):
            continue
        spellings.add(r[5].strip())
        out["active" if r[1] == "A" else "inactive"].add(r[4].strip())
    return out, sorted(spellings)


def substances_for(firm: str) -> list[str]:
    """Active Type II DMF subjects filed by a firm whose name matches `firm`.

    Matched on the DISTINCTIVE core of the name, so `CENTRIENT PHARMACEUTICALS
    INDIA PRIVATE LIMITED` finds `Centrient Pharmaceuticals India Pvt Ltd`
    without a hand-written alias table.
    """
    fetch(DMF_URL, DMF_XLSX)
    want = core_tokens(normalize(firm))
    if not want:
        return []
    it = xlsx_rows(DMF_XLSX)
    next(it)
    found: dict[str, str] = {}
    for r in it:
        if len(r) < 6 or r[2] != "II" or r[1] != "A" or not (r[4] and r[5]):
            continue
        have = core_tokens(normalize(r[4]))
        if have and len(want & have) / len(want | have) >= 0.5:
            found.setdefault(squash(r[5]), r[5].strip())
    return sorted(found.values())


def decrs_rows() -> list[dict]:
    fetch(DECRS_URL, DECRS_ZIP)
    with zipfile.ZipFile(DECRS_ZIP) as z:
        lines = z.read("drls_reg.txt").decode("utf-8", errors="replace").splitlines()
    hdr = [h.strip() for h in lines[0].split("\t")]
    return [dict(zip(hdr, [c.strip() for c in l.split("\t")])) for l in lines[1:] if l.strip()]


def _iso3(addr: str) -> str | None:
    m = re.findall(r"\(([A-Z]{3})\)", addr or "")
    return m[-1] if m else None


def build_index():
    """Firms that can make things, and the risk we already know about them."""
    rows = decrs_rows()
    # Keyed by the FULL normalised firm name, NOT by core tokens. Keying by core
    # merged every "United Laboratories" site into one record - Zhuhai, Chengdu
    # and Inner Mongolia pooled their FEIs, so a lookup returned one candidate
    # carrying three plants' enforcement history and there was no tie left for
    # the ambiguity guard to catch. The conflation happened in the index, before
    # matching ever ran.
    by_core: dict[str, dict] = {}
    for r in rows:
        name = r.get("FIRM_NAME") or ""
        full = " ".join(normalize(name))
        if not full or not core_tokens(normalize(name)):
            continue
        rec = by_core.setdefault(full, {
            "name": name, "core": frozenset(core_tokens(normalize(name))),
            "feis": set(), "countries": set(), "api": False, "operations": set(),
        })
        rec["feis"].add((r.get("FEI_NUMBER") or "").strip())
        c = _iso3(r.get("ADDRESS"))
        if c:
            rec["countries"].add(c)
        ops = r.get("OPERATIONS") or ""
        rec["operations"].update(o.strip() for o in ops.split(";") if o.strip())
        if "API MANUFACTURE" in ops:
            rec["api"] = True

    sig = defaultdict(list)
    p = REPO / "web" / "data" / "signals.json"
    if p.exists():
        for s in json.loads(p.read_text()):
            if s["node_id"].startswith("facility:fei:"):
                sig[s["node_id"].rsplit(":", 1)[1]].append(s)
    return by_core, sig


AMBIGUITY_MARGIN = 0.05


def _match(name: str, by_core) -> tuple[dict | None, str]:
    """Locate a DMF holder in DECRS, REFUSING when the name is ambiguous.

    The first version took the best Jaccard score, and it reproduced benchmark
    FP #17 live: `UNITED LABORATORIES CHENGDU` and `THE UNITED LABORATORIES
    (INNER MONGOLIA)` both collapsed onto Zhuhai United Laboratories and inherited
    its four OAIs. Two plants that may be clean were shown carrying a third
    plant's enforcement history - on a screen a buyer is meant to act on.

    entity_resolution.resolve() exists precisely to refuse that, and this is the
    same rule: if two candidates tie, return nothing and say why.
    """
    core = core_tokens(normalize(name))
    if not core:
        return None, "no distinctive tokens"
    scored = sorted(
        ((len(core & rec["core"]) / len(core | rec["core"]), rec)
         for rec in by_core.values() if rec["core"]),
        key=lambda t: -t[0])
    if not scored or scored[0][0] < 0.5:
        return None, "not found in DECRS — capability unverified"
    top = scored[0][0]
    tied = [r for sc, r in scored if top - sc < AMBIGUITY_MARGIN]
    if len(tied) > 1:
        names = ", ".join(sorted({(r["name"] or "?")[:28] for r in tied})[:2])
        return None, f"⚠️ AMBIGUOUS in DECRS ({len(tied)} firms tie: {names}) — not attributing risk"
    return scored[0][1], "matched"


def alternates(substance_key: str, exclude: str | None = None, cutoff: date | None = None):
    """Everyone with an ACTIVE DMF for this substance, scored as a re-route target."""
    by_core, sig = build_index()
    groups, spellings = dmf_holders(substance_key)
    holders = groups["active"]
    if not holders and not groups["inactive"]:
        raise SystemExit(f"no DMF holders match {substance_key!r}")

    out = []
    for h in sorted(holders):
        if exclude and exclude.lower() in h.lower():
            continue
        rec, match_note = _match(h, by_core)
        countries = sorted(rec["countries"]) if rec else []
        feis = sorted(f for f in (rec["feis"] if rec else set()) if f)

        risk = []
        for f in feis:
            for s in sig.get(f, []):
                if s["kind"] == "inspection_classification" and s["payload"].get("classification") == "OAI":
                    risk.append(f"OAI {s['observed_at']}")
                elif s["kind"] == "import_refusal" and s["severity"] == "high":
                    risk.append(f"cGMP refusal {s['observed_at']}")

        in_choke = bool(set(countries) & CHOKEPOINT_ISO3)
        taa = None
        if countries:
            if all(c in TAA_DESIGNATED_ISO3 for c in countries):
                taa = True
            elif all(c in NOT_DESIGNATED for c in countries):
                taa = False

        score = 0.0
        why = []
        if rec and rec["api"]:
            score += 3.0; why.append("registered API manufacturer")
        elif rec:
            score += 1.0; why.append("registered establishment, not flagged API")
        else:
            why.append(match_note)
        # A multinational may hold sites on both sides of the line. Saying
        # "Sandoz GmbH is in the chokepoint region" because it also runs an
        # Indian plant is wrong and would mislead a buyer; report the split.
        clean = [c for c in countries if c not in CHOKEPOINT_ISO3]
        if clean and in_choke:
            score += 1.0
            why.append(f"mixed footprint: {'/'.join(clean)} AND {'/'.join(sorted(set(countries) & CHOKEPOINT_ISO3))}"
                       " — sourcing depends on which site")
        elif clean:
            score += 2.0; why.append(f"outside CN/IN ({'/'.join(clean)})")
        elif in_choke:
            why.append(f"⚠️ same chokepoint region ({'/'.join(countries)})")
        if taa is True:
            score += 1.5; why.append("TAA-designated — federally procurable")
        elif taa is False and not clean:
            why.append("not TAA-designated — VA/DoD cannot buy")
        elif taa is False:
            why.append("TAA depends on the site of manufacture, not the parent")
        if risk:
            score -= 2.0 * len(set(risk)); why.append(f"🔴 own risk: {', '.join(sorted(set(risk))[:3])}")

        out.append({"holder": h, "matched_firm": rec["name"] if rec else None,
                    "countries": countries, "feis": feis[:3], "score": round(score, 1),
                    "risk_flags": sorted(set(risk)), "why": why})
    out.sort(key=lambda r: -r["score"])
    return out, groups, spellings


# --------------------------------------------------------------------------
# Route mapping — the path, not just the shortlist
# --------------------------------------------------------------------------


def load_graph() -> tuple[dict, list]:
    d = REPO / "web" / "data"
    nodes, edges = {}, []
    for f in ("nodes.openfda.json", "nodes.curated.json", "nodes.signals.json"):
        if (d / f).exists():
            for n in json.loads((d / f).read_text()):
                nodes[n["id"]] = n
    for f in ("edges.openfda.json", "edges.curated.json", "edges.signals.json"):
        if (d / f).exists():
            edges += json.loads((d / f).read_text())
    return nodes, edges


def downstream(start: str, edges: list, rels=("feeds", "active_in", "formulated_into")) -> dict:
    """Everything that depends on `start`, by node type.

    Edges point the way material flows, so dependants are reached by following
    OUTGOING edges - the same direction graph.ts walks for the cascade.
    """
    out = defaultdict(list)
    for e in edges:
        out[e["src"]].append(e)
    seen, order, stack = set(), [], [start]
    while stack:
        cur = stack.pop()
        for e in out.get(cur, []):
            if e["rel"] in rels and e["dst"] not in seen:
                seen.add(e["dst"])
                order.append((cur, e["rel"], e["dst"]))
                stack.append(e["dst"])
    return {"edges": order, "nodes": seen}


def route(substance: str, graph_node: str | None = None, exclude: str | None = None) -> dict:
    """A supplier goes down. What breaks, and what is the path around it?"""
    nodes, edges = load_graph()
    rows, groups, spellings = alternates(substance, exclude=exclude)

    # Which graph node is this substance?
    node = graph_node
    if not node:
        sq = squash(substance)
        for nid, n in nodes.items():
            if nid.split(":", 1)[0] in ("precursor", "api") and (
                    squash(n.get("label") or nid.split(":", 1)[1]).startswith(sq[:12])
                    or sq.startswith(squash(n.get("label") or "")[:12])):
                node = nid
                break

    impact = downstream(node, edges) if node else {"edges": [], "nodes": set()}
    drugs = sorted(n for n in impact["nodes"] if n.startswith("drug:"))
    products = [n for n in impact["nodes"] if n.startswith("product:")]
    viable = [r for r in rows if r["score"] > 0]

    return {"substance": substance, "graph_node": node, "excluded": exclude,
            "affected_drugs": drugs, "affected_products": len(products),
            "alternates": rows, "viable": viable,
            "active_holders": len(groups["active"]), "spellings": len(spellings)}


def report_route(r: dict) -> None:
    print(f"AEGIS ROUTE — {r['substance']}")
    if r["excluded"]:
        print(f"  DOWN: {r['excluded']}")
    if not r["graph_node"]:
        print("  ⚠️ this substance is not a node in the graph — impact not traced\n")
    else:
        print(f"  node: {r['graph_node']}")
        print(f"  IMPACT: {len(r['affected_drugs'])} drug(s), {r['affected_products']} product(s)")
        print(f"          {', '.join(d.split(':')[1] for d in r['affected_drugs'])}\n")

    if not r["viable"]:
        print("  🔴 NO VIABLE RE-ROUTE. Every alternate is unregistered, inside the")
        print("     same chokepoint, or carries its own enforcement history.\n")
    else:
        print(f"  {len(r['viable'])} candidate route(s), best first:\n")
        for i, a in enumerate(r["viable"][:5], 1):
            c = "/".join(a["countries"]) or "?"
            print(f"   {i}. {a['holder'][:44]}  [{c}]  score {a['score']}")
            hop = r["graph_node"] or "?"
            path = " → ".join([a["holder"][:22], hop] +
                              [d.split(":")[1] for d in r["affected_drugs"][:3]])
            print(f"      path: {path}")
            print(f"      {a['why'][0]}")
    print(f"\n  ❌ capacity · lead time · willingness to supply — no public source. "
          f"Shortlist, not allocation.")


def report(substance: str, result, disrupted: str | None) -> None:
    rows, groups, spellings = result
    print(f"AEGIS — alternate suppliers for {substance!r}")
    if disrupted:
        print(f"  disrupted supplier excluded: {disrupted}")
    print(f"  matched {len(spellings)} spelling variant(s) of this substance in the register")
    print(f"  {len(groups['active'])} ACTIVE DMF holders  ({len(groups['inactive'])} inactive, "
          f"not shown - a lapsed filing is not a supplier you can call)\n")
    if not rows:
        print("  🔴 NO ALTERNATES with an active DMF. This substance has no re-route.\n")
        return
    print(f"  {'#':>3} {'score':>6}  {'country':<10}{'holder':<44}notes")
    for i, r in enumerate(rows[:12], 1):
        c = "/".join(r["countries"]) or "?"
        print(f"  {i:>3} {r['score']:>6.1f}  {c:<10}{r['holder'][:42]:<44}{r['why'][0]}")
        for extra in r["why"][1:]:
            print(f"      {'':>6}  {'':<10}{'':<44}{extra}")
    print("""
  ❌ NOT MODELLED, and no public source exists for any of it:
     capacity · lead time · willingness to supply · current utilisation
  This is a procurement SHORTLIST, not an allocation. Anyone presenting it as an
  optimiser is claiming data that does not exist - see DATA.md, Gaps.""")
    outside = [r for r in rows if r["countries"] and not (set(r["countries"]) & CHOKEPOINT_ISO3)]
    verified = [r for r in rows if r["matched_firm"]]
    print(f"\n  THE NUMBER THAT MATTERS: of {len(rows)} active holders, {len(verified)} are "
          f"registered\n  US establishments and {len(outside)} of those sit outside China/India.")


ANCHORS = {
    "6-aminopenicillanic acid": {"min_active": 8, "node": "precursor:6-apa", "drugs": 6},
    "oxacillin": {"max_active": 6},          # must NOT pull in cloxacillin holders
}


def selftest() -> int:
    """Assert the things that would fail silently. Run before trusting output."""
    ok = True
    print("AEGIS self-check\n")

    g, sp = dmf_holders("6-aminopenicillanic acid")
    n = len(g["active"])
    good = n >= 8
    ok &= good
    print(f"  [{'OK ' if good else 'FAIL'}] 6-APA active holders {n} (>=8; squash must "
          f"bridge {len(sp)} spellings)")

    g2, _ = dmf_holders("oxacillin")
    bleed = [h for h in g2["active"]]
    clean = len(g2["active"]) <= 6
    ok &= clean
    print(f"  [{'OK ' if clean else 'FAIL'}] oxacillin active holders {len(g2['active'])} "
          f"(<=6; boundary check must exclude CLOXACILLIN)")

    r = route("6-aminopenicillanic acid")
    node_ok = r["graph_node"] == "precursor:6-apa"
    ok &= node_ok
    print(f"  [{'OK ' if node_ok else 'FAIL'}] 6-APA resolves to {r['graph_node']}")
    drugs_ok = len(r["affected_drugs"]) == 6
    ok &= drugs_ok
    print(f"  [{'OK ' if drugs_ok else 'FAIL'}] cascade reaches {len(r['affected_drugs'])} "
          f"drugs (expect 6)")

    rows, _, _ = alternates("6-aminopenicillanic acid")
    amb = [x for x in rows if any("AMBIGUOUS" in w for w in x["why"])]
    amb_ok = len(amb) >= 1
    ok &= amb_ok
    print(f"  [{'OK ' if amb_ok else 'FAIL'}] ambiguity guard refuses {len(amb)} holder(s) "
          f"rather than attributing another plant's risk")

    outside = [x for x in rows if x["matched_firm"] and x["countries"]
               and not (set(x["countries"]) & CHOKEPOINT_ISO3)]
    print(f"\n  headline: {len(rows)} active 6-APA holders, "
          f"{len([x for x in rows if x['matched_firm']])} DECRS-registered, "
          f"{len(outside)} outside CN/IN")
    print(f"\n  {'all checks passed' if ok else 'SELF-CHECK FAILED'}")
    return 0 if ok else 1


def main() -> int:
    args = sys.argv[1:]
    if "--selftest" in args:
        return selftest()
    if "--demo" in args:
        subs = ["6 aminopenicillanic acid", "amoxicillin trihydrate"]
        for s in subs:
            try:
                report(s, alternates(s), None)
                print()
            except SystemExit as e:
                print(f"  {e}\n")
        return 0
    if "--substance" in args:
        s = args[args.index("--substance") + 1]
        excl = args[args.index("--exclude") + 1] if "--exclude" in args else None
        report(s, alternates(s, exclude=excl), excl)
        return 0
    if "--route" in args:
        sub = args[args.index("--route") + 1]
        excl = args[args.index("--exclude") + 1] if "--exclude" in args else None
        r = route(sub, exclude=excl)
        report_route(r)
        if "--write" in args:
            out = REPO / "web" / "data" / "reroute.json"
            out.write_text(json.dumps(r, indent=2) + "\n")
            print(f"\n  wrote {out.relative_to(REPO)}")
        return 0
    if "--facility" in args:
        fei = args[args.index("--facility") + 1]
        by_core, sig = build_index()
        rows = decrs_rows()
        hit = next((r for r in rows if (r.get("FEI_NUMBER") or "").strip() == fei), None)
        if not hit:
            raise SystemExit(f"FEI {fei} not in DECRS")
        name = hit.get("FIRM_NAME")
        print(f"AEGIS — DISRUPTED: {name}  (FEI {fei}, {_iso3(hit.get('ADDRESS'))})\n")
        mine = substances_for(name)
        if not mine:
            raise SystemExit(f"no active Type II DMF substances traced to {name!r}")
        print(f"holds {len(mine)} active DMF substance(s): {', '.join(mine[:4])}\n")
        for s in mine[:3]:
            report(s, alternates(s, exclude=name), name)
            print()
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
