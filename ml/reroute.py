"""Re-route — when a supplier goes down, who else can make this?

    python3 ml/reroute.py --facility 3004497364     # Centrient India goes down
    python3 ml/reroute.py --substance "amoxicillin trihydrate"
    python3 ml/reroute.py --demo                    # the 6-APA cascade

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
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.entity_resolution import core_tokens, normalize  # noqa: E402
from ml.upstream import DECRS_URL, DECRS_ZIP, EXCEL_EPOCH, fetch  # noqa: E402
from ml.xlsx import rows as xlsx_rows  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

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
    fetch("https://www.fda.gov/media/192069/download?attachment",
          REPO / "data" / "cache" / "dmf" / "dmf.xlsx")
    it = xlsx_rows(REPO / "data" / "cache" / "dmf" / "dmf.xlsx")
    next(it)
    want = squash(substance)
    out = {"active": set(), "inactive": set()}
    spellings: set[str] = set()
    for r in it:
        if len(r) < 6 or r[2] != "II" or not (r[4] and r[5]):
            continue
        sq = squash(r[5])
        if want not in sq and sq not in want:
            continue
        spellings.add(r[5].strip())
        out["active" if r[1] == "A" else "inactive"].add(r[4].strip())
    return out, sorted(spellings)


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


def report(substance: str, result, disrupted: str | None) -> None:
    rows, groups, spellings = result
    print(f"RE-ROUTE — alternate suppliers for {substance!r}")
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


def main() -> int:
    args = sys.argv[1:]
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
    if "--facility" in args:
        fei = args[args.index("--facility") + 1]
        by_core, sig = build_index()
        rows = decrs_rows()
        hit = next((r for r in rows if (r.get("FEI_NUMBER") or "").strip() == fei), None)
        if not hit:
            raise SystemExit(f"FEI {fei} not in DECRS")
        name = hit.get("FIRM_NAME")
        print(f"DISRUPTED: {name}  (FEI {fei}, {_iso3(hit.get('ADDRESS'))})\n")
        subs = substances_before(date.today())
        mine = [k for k, hs in subs.items()
                if any(len(core_tokens(normalize(h)) & core_tokens(normalize(name)))
                       >= max(1, len(core_tokens(normalize(name))) - 1) for h in hs)]
        if not mine:
            raise SystemExit(f"no DMF substances traced to {name!r}")
        print(f"holds DMFs for {len(mine)} substance(s): {', '.join(sorted(mine)[:6])}\n")
        for s in sorted(mine)[:3]:
            report(s, alternates(s, exclude=name), name)
            print()
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
