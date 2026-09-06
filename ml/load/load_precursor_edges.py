#!/usr/bin/env python3
"""Layer 3 — the 6-APA precursor node and the six-penicillin fan-out.

    python3 ml/load/load_precursor_edges.py

It owns the precursor node and the fan-out:

    precursor:6-apa --feeds--> api:*     the six penicillins, layer 3

Genuinely layer 3, and it stays that way: **no dataset carries the API-to-precursor
relationship.** It is chemistry, hand-curated from published synthesis routes and
cited to the CFR Pharma Choke Point report. That missing layer is the point — it is
the gap we name on stage and the thing a grant would fund.

The 8 DMF holders used to live here as hand-typed rows. They now come from
`load_dmf.py`, because 6 of 8 hand-typed names normalised to different ids than the
register's own spelling ('...PVT LTD' vs '...PRIVATE LTD'), which would have
produced 16 producer nodes where there are 8.

NCPC Hebei Huamin (DMF 17694) is INACTIVE, not absent — recorded in the precursor
node's attrs with deliberately no edge, so it cannot inflate the producer count.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import io_helpers as io  # noqa: E402

CFR_URL = "https://www.cfr.org/reports/the-pharma-choke-point"

FEEDS_CITATION = (
    "Council on Foreign Relations, 'The Pharma Choke Point' — 6-APA is the shared "
    f"beta-lactam nucleus from which the semisynthetic penicillins are made. {CFR_URL}"
)

# ⚠️ OPEN COUPLING: these ids must match the api: nodes Nikhil emits from openFDA,
# or the fan-out silently produces nothing. api:amoxicillin-trihydrate is pinned by
# the shared contract and his brief; the other five are not pinned anywhere, so they
# are the plain ingredient name until he confirms. The validator's "referenced but
# not declared" warning is the tripwire.
PENICILLINS = [
    {"drug": "Amoxicillin",   "api": "api:amoxicillin-trihydrate", "eo13944": True},
    {"drug": "Ampicillin",    "api": "api:ampicillin",             "eo13944": True},
    {"drug": "Piperacillin",  "api": "api:piperacillin",           "eo13944": True},
    {"drug": "Dicloxacillin", "api": "api:dicloxacillin",          "eo13944": False},
    {"drug": "Nafcillin",     "api": "api:nafcillin",              "eo13944": False},
    {"drug": "Oxacillin",     "api": "api:oxacillin",              "eo13944": False},
]


def main() -> int:
    precursor = io.node(
        "precursor:6-apa", type="precursor",
        label="6-Aminopenicillanic acid (6-APA)",
        attrs={
            "feeds_drugs": [p["drug"] for p in PENICILLINS],
            "eo13944_note": "4 penicillins are on the EO 13944 essential medicines "
                            "list; 3 of the 6 we trace to 6-APA. Penicillin G is a "
                            "7th derivative, not one of the six. The numerator and "
                            "denominator count different things — do not collapse them.",
            "inactive_holders": [
                {"dmf": 17694, "holder": "NCPC HEBEI HUAMIN PHARMACEUTICAL CO LTD",
                 "status": "I", "filed": "2004-09-09",
                 "note": "inactive, not absent — say inactive, it is sharper and true"},
            ],
            "source": "hand-curated from published synthesis routes",
            "source_url": CFR_URL,
        })

    edges = [io.edge("precursor:6-apa", p["api"], "feeds", 3, FEEDS_CITATION)
             for p in PENICILLINS]

    io.write_nodes([precursor])
    io.write_edges(edges)

    on_list = sum(p["eo13944"] for p in PENICILLINS)
    print(f"precursor:6-apa + {len(edges)} feeds edge(s), layer 3")
    print(f"  fan-out: {len(PENICILLINS)} penicillins, {on_list} of them on EO 13944")
    print("  (4 penicillins are on the list; 3 of OUR 6 — Penicillin G is the 4th)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
