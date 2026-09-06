#!/usr/bin/env python3
"""Layer 3 — the hand-curated 6-APA precursor edges.

    python3 ml/load/load_precursor_edges.py

These are the edges the cascade runs on and the ones a judge will probe, so every
row carries its citation. Two families:

  1. precursor:6-apa --produced_by--> company:*   the 8 active US Type II DMF holders
  2. precursor:6-apa --feeds-->       api:*       the six penicillins that fan out

Layer 3, not 2: these rows are typed in from the DMF register, not parsed from it.
`load_dmf.py` re-emits the same (src, dst, rel) keys at layer 2 once it genuinely
parses the workbook, and the harness merges the layer down. Calling them layer 2
today would claim a parse that has not happened.

Counts, and say them exactly this way:
  * 8 active filings, at most 7 owners — United Laboratories Chengdu and
    Inner Mongolia share a parent. Render owners, not filings, or the graph
    overstates diversity.
  * 4 of the 8 are Chinese.
  * NCPC Hebei Huamin (DMF 17694) is INACTIVE, not absent. It is recorded in the
    precursor node's attrs and deliberately has no edge, so it cannot inflate the
    producer count.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import io_helpers as io  # noqa: E402

DMF_URL = "https://www.fda.gov/media/192069/download?attachment"
DMF_SOURCE = "FDA Type II DMF register, sheet 2Q2026-EXCEL"
DECRS_SOURCE = "FDA DECRS drls_reg, Sep 4 2026"
DECRS_URL = "https://www.accessdata.fda.gov/cder/drls_reg.zip"
CFR_URL = "https://www.cfr.org/reports/the-pharma-choke-point"

# The corrected eight. ANTIBIOTICOS SA was missed by naive substring matching
# because its SUBJECT reads "6-AMINO PENICILLANIC ACID" — with a space.
# country=None means unverified: do NOT assert it.
HOLDERS = [
    {"dmf": 8757,  "holder": "SANDOZ GMBH",
     "country": "at", "filed": "1990", "country_evidence": "DECRS 'Sandoz GmbH' = AUT"},
    {"dmf": 12348, "holder": "ANTIBIOTICOS SA",
     "country": None, "filed": "1997",
     "country_evidence": "NOT in DECRS. Only 'Antibioticos do Brasil Ltda' (BRA) "
                         "matches, a different entity. Spain is likely but unverified — "
                         "do not assert it."},
    {"dmf": 18525, "holder": "PURE AND CURE HEALTHCARE PVT LTD",
     "country": "in", "filed": "2005", "country_evidence": "DECRS = IND"},
    {"dmf": 19525, "holder": "INNER MONGOLIA CHANGSHENG",
     "country": "cn", "filed": "2006", "country_evidence": "DECRS = CHN"},
    {"dmf": 21994, "holder": "UNITED LABORATORIES CHENGDU",
     "country": "cn", "filed": "2008", "parent": "The United Laboratories",
     "country_evidence": "partial — DECRS carries TUL Inner Mongolia and Zhuhai "
                         "(both CHN), not the Chengdu site"},
    {"dmf": 27248, "holder": "THE UNITED LABORATORIES INNER MONGOLIA",
     "country": "cn", "filed": "2013", "parent": "The United Laboratories",
     "country_evidence": "DECRS = CHN"},
    {"dmf": 30779, "holder": "SINOPHARM WEIQIDA",
     "country": "cn", "filed": "2016", "country_evidence": "DECRS = CHN",
     "state_owned": True},
    {"dmf": 40387, "holder": "APITORIA PHARMA PVT LTD",
     "country": "in", "filed": "2024", "country_evidence": "DECRS = IND"},
]

COUNTRY_LABELS = {"at": "Austria", "in": "India", "cn": "China"}

# ⚠️ OPEN COUPLING: these ids must match the api: nodes Nikhil emits from
# openFDA, or the fan-out silently produces nothing. api:amoxicillin-trihydrate
# is pinned by the shared contract and his brief; the other five are not pinned
# anywhere, so they are the plain ingredient name until he confirms. The
# validator's "referenced but not declared" warning is the tripwire.
PENICILLINS = [
    {"drug": "Amoxicillin",    "api": "api:amoxicillin-trihydrate", "eo13944": True},
    {"drug": "Ampicillin",     "api": "api:ampicillin",             "eo13944": True},
    {"drug": "Piperacillin",   "api": "api:piperacillin",           "eo13944": True},
    {"drug": "Dicloxacillin",  "api": "api:dicloxacillin",          "eo13944": False},
    {"drug": "Nafcillin",      "api": "api:nafcillin",              "eo13944": False},
    {"drug": "Oxacillin",      "api": "api:oxacillin",              "eo13944": False},
]

FEEDS_CITATION = (
    "Council on Foreign Relations, 'The Pharma Choke Point' — 6-APA is the shared "
    f"beta-lactam nucleus from which the semisynthetic penicillins are made. {CFR_URL}"
)


def main() -> int:
    nodes, edges = [], []

    for h in HOLDERS:
        node_id, resolved_by = io.company_id(name=h["holder"])
        attrs = {
            "dmf": h["dmf"],
            "dmf_status": "A",
            "dmf_filed": h["filed"],
            "dmf_subject_normalised": "6-aminopenicillanic acid",
            "country_evidence": h["country_evidence"],
            "source": DMF_SOURCE,
        }
        if h.get("parent"):
            # 8 filings, at most 7 owners. Render owners, not filings.
            attrs["parent"] = h["parent"]
        if h.get("state_owned"):
            # State ownership and 1260H designation are different things.
            attrs["state_owned"] = True
        if h["country"] is None:
            attrs["country_unverified"] = True

        nodes.append(io.node(node_id, type="company", label=h["holder"],
                             country=h["country"], attrs=attrs,
                             resolved_by=resolved_by))

        edges.append(io.edge(
            "precursor:6-apa", node_id, "produced_by", 3,
            f"{DMF_SOURCE} — DMF {h['dmf']}, holder '{h['holder']}', status A, "
            f"Type II, filed {h['filed']}, SUBJECT normalises to "
            f"'6-aminopenicillanic acid'. {DMF_URL}"))

        if h["country"]:
            country_node = io.country_id(h["country"])
            nodes.append(io.node(country_node, type="country",
                                 label=COUNTRY_LABELS[h["country"]],
                                 country=h["country"],
                                 attrs={"source": DECRS_SOURCE}))
            edges.append(io.edge(
                node_id, country_node, "incorporated_in", 3,
                f"{DECRS_SOURCE} — {h['country_evidence']}. {DECRS_URL}"))

    for p in PENICILLINS:
        edges.append(io.edge("precursor:6-apa", p["api"], "feeds", 3, FEEDS_CITATION))

    n_nodes = io.write_nodes(nodes)
    n_edges = io.write_edges(edges)

    chinese = sum(1 for h in HOLDERS if h["country"] == "cn")
    owners = len({h.get("parent") or h["holder"] for h in HOLDERS})
    print(f"nodes.curated.json  {n_nodes} row(s)")
    print(f"edges.curated.json  {n_edges} row(s)")
    print(f"6-APA: {len(HOLDERS)} active filings, at most {owners} owners, "
          f"{chinese} Chinese")
    print(f"fan-out: {len(PENICILLINS)} penicillins "
          f"({sum(p['eo13944'] for p in PENICILLINS)} on EO 13944)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
