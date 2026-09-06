#!/usr/bin/env python3
"""Layer 2 — the FDA Type II Drug Master File register.

    ml/.venv/bin/python ml/load/load_dmf.py

Type II = drug substances, filed by API manufacturers and CMOs. This is the one
source in the whole project that crosses the drug-to-company boundary **with no
fuzzy matching at all**, because SUBJECT (the API) and HOLDER sit in the same row.
Every other route from a drug to a factory goes through a name match that is right
42% of the time.

It owns the 8 active 6-APA holders end to end — nodes, produced_by edges, and the
curated country attribution — so the ids come from the register rather than from
anyone's typing. `load_precursor_edges.py` owns the fan-out (precursor -> api).

## Two different matchers, for two different traps

**6-APA needs squashing.** The register spells one molecule eight ways, and
ANTIBIOTICOS SA writes `6-AMINO PENICILLANIC ACID` with a space where the others
hyphenate. Matching `AMINOPENICILLANIC` against squash(SUBJECT) finds all 8;
matching the raw string finds 5. That missing row is a headline number.

**Drug names need word boundaries.** `OXACILLIN` is a substring of CLOXACILLIN,
DICLOXACILLIN and FLUCLOXACILLIN, so a naive contains-check overcounts it 9 to 5.
Squashing makes this *worse*, not better, because it destroys the word boundary —
`SODIUM OXACILLIN` becomes `SODIUMOXACILLIN`. So drug matching runs on the
original text with \\b.

Use squash for spelling variants of one molecule; use boundaries for one name
inside another. They are not interchangeable.
"""

from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import io_helpers as io  # noqa: E402

DMF_URL = "https://www.fda.gov/media/192069/download?attachment"
DMF_SOURCE = "FDA Type II DMF register, sheet 2Q2026-EXCEL"
CACHE = HERE.parent / "cache" / "dmf.xlsx"
SHEET = "2Q2026-EXCEL"

# Country is NOT in the DMF register — it has no country column at all. These are
# hand-verified against DECRS (see brain: project/datasets/layer2-official-lists.md)
# and keyed by DMF number so they survive any change in holder spelling.
# Emitted at layer 3 and superseded at layer 2 when load_decrs.py runs.
CURATED_COUNTRY = {
    8757:  ("at", "DECRS 'Sandoz GmbH' = AUT"),
    12348: (None, "NOT in DECRS. Only 'Antibioticos do Brasil Ltda' (BRA) matches, a "
                  "different entity. Spain is likely but unverified — do not assert it."),
    18525: ("in", "DECRS = IND"),
    19525: ("cn", "DECRS = CHN"),
    21994: ("cn", "partial — DECRS carries TUL Inner Mongolia and Zhuhai (both CHN), "
                  "not the Chengdu site"),
    27248: ("cn", "DECRS = CHN"),
    30779: ("cn", "DECRS = CHN"),
    40387: ("in", "DECRS = IND"),
}

# 8 filings, at most 7 owners. Render owners, not filings, or the graph
# overstates diversity.
CURATED_PARENT = {
    21994: "The United Laboratories",
    27248: "The United Laboratories",
}

# Sinopharm is state-owned AND absent from 1260H. Those are different things.
CURATED_STATE_OWNED = {30779}

COUNTRY_LABELS = {"at": "Austria", "in": "India", "cn": "China"}

# The six we trace to 6-APA. eo13944 is what load_eo13944.py confirms; recorded
# here only to keep the "4 on the list, 3 of our 6" distinction visible.
PENICILLINS = ["AMOXICILLIN", "AMPICILLIN", "PIPERACILLIN",
               "DICLOXACILLIN", "NAFCILLIN", "OXACILLIN"]


def squash(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def fetch() -> Path:
    if CACHE.exists():
        return CACHE
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        DMF_URL, headers={"User-Agent": "Mozilla/5.0 (CHOKEPOINT/DNHacks research)"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        CACHE.write_bytes(resp.read())
    return CACHE


def read_rows() -> list[tuple]:
    try:
        import openpyxl
    except ModuleNotFoundError:
        sys.exit("openpyxl missing — run: python3 -m venv ml/.venv && "
                 "ml/.venv/bin/pip install -r ml/requirements.txt")
    wb = openpyxl.load_workbook(fetch(), read_only=True, data_only=True)
    rows = wb[SHEET].iter_rows(values_only=True)
    next(rows)  # header: DMF# STATUS TYPE 'SUBMIT DATE' HOLDER SUBJECT + 12 empty
    return [r for r in rows if r[2] is not None]


def main() -> int:
    rows = read_rows()
    type_ii = [r for r in rows if r[2] == "II"]
    active = [r for r in type_ii if r[1] == "A"]
    # 4 holder names carry stray leading/trailing whitespace (one in three
    # variants). Raw distinct is 2,276; stripped is 2,271. Strip, then count.
    holders = {(r[4] or "").strip() for r in active}

    print(f"{DMF_SOURCE}")
    print(f"  {len(rows):,} data rows -> {len(type_ii):,} Type II -> "
          f"{len(active):,} active -> {len(holders):,} distinct holders")

    apa = sorted((r for r in active if "AMINOPENICILLANIC" in squash(r[5])),
                 key=lambda r: r[0])
    naive = [r for r in active if "AMINOPENICILLANIC" in (r[5] or "").upper()]
    print(f"  6-APA: {len(apa)} active filings (raw substring finds only {len(naive)})")

    nodes, edges = [], []
    for r in apa:
        dmf, holder, subject = r[0], (r[4] or "").strip(), r[5]
        country, evidence = CURATED_COUNTRY.get(dmf, (None, "not cross-referenced"))
        node_id, resolved_by = io.company_id(name=holder)

        attrs = {
            "dmf": dmf,
            "dmf_status": "A",
            "dmf_type": "II",
            "dmf_filed": str(r[3])[:10] if r[3] else None,
            "dmf_subject": subject.strip() if subject else None,
            "country_evidence": evidence,
            "source": DMF_SOURCE,
            "source_url": DMF_URL,
        }
        if dmf in CURATED_PARENT:
            attrs["parent"] = CURATED_PARENT[dmf]
        if dmf in CURATED_STATE_OWNED:
            attrs["state_owned"] = True
        if country is None:
            attrs["country_unverified"] = True

        nodes.append(io.node(node_id, type="company", label=holder, country=country,
                             attrs=attrs, resolved_by=resolved_by))
        edges.append(io.edge(
            "precursor:6-apa", node_id, "produced_by", 2,
            f"{DMF_SOURCE} — DMF {dmf}, holder '{holder}', status A, Type II, "
            f"SUBJECT {subject.strip()!r}. {DMF_URL}"))

        if country:
            cid = io.country_id(country)
            nodes.append(io.node(cid, type="country", label=COUNTRY_LABELS[country],
                                 country=country,
                                 attrs={"source": "DECRS cross-reference (curated)"}))
            # Layer 3: the DMF register has no country column. load_decrs.py
            # supersedes this at layer 2.
            edges.append(io.edge(node_id, cid, "incorporated_in", 3,
                                 f"DECRS cross-reference — {evidence}"))

    # Per-drug denominators: drug and holder in the same row, no fuzzy matching.
    # This is the backtest denominator DECRS cannot supply.
    print("  per-drug (active Type II, word-boundary matched):")
    for name in PENICILLINS:
        pattern = re.compile(rf"\b{name}", re.I)
        hits = [r for r in active if pattern.search(r[5] or "")]
        loose = [r for r in active if name in squash(r[5])]
        note = f"  (naive substring would say {len(loose)})" if len(loose) != len(hits) else ""
        distinct = {(r[4] or "").strip() for r in hits}
        print(f"    {name.title():<14} {len(hits):>3} filings  {len(distinct):>3} holders{note}")
        nodes.append(io.node(
            io.drug_id(name), type="drug", label=name.title(),
            attrs={"active_dmfs": len(hits), "distinct_dmf_holders": len(distinct),
                   "dmf_denominator_source": DMF_SOURCE}))

    n_nodes = io.write_nodes(nodes)
    n_edges = io.write_edges(edges)

    chinese = sum(1 for r in apa if CURATED_COUNTRY.get(r[0], (None,))[0] == "cn")
    owners = len({CURATED_PARENT.get(r[0]) or (r[4] or "").strip() for r in apa})
    print(f"\n  nodes.curated.json {n_nodes} row(s), edges.curated.json {n_edges} row(s)")
    print(f"  6-APA: {len(apa)} filings, at most {owners} owners, {chinese} Chinese")
    return 0


if __name__ == "__main__":
    sys.exit(main())
