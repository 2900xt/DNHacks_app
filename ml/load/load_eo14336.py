#!/usr/bin/env python3
"""Layer 2b — EO 14336 (SAPIR). Metadata only. NOT a dataset.

    python3 ml/load/load_eo14336.py

❗ **Nothing in the graph keys off this.** It is a citation and a mandate — four
sections of policy text directing ASPR to stockpile six months of API for ~26
critical drugs and maintain a plan for 86 essential medicines. There is no table
in it, no entity list, nothing to join on.

So this loader deliberately emits **no nodes and no edges.** It pins the Federal
Register metadata to disk so the citation on a slide is verbatim and checkable, and
it asserts the one fact our documents kept getting wrong.

⚠️ **August 2025, not 2026.** Signed Aug 13 2025, published Aug 19 2025, 90 FR
40223. Several files in the brain had the year wrong; this asserts it so the error
cannot come back.

⚠️ **Do not let this appear on a data slide as though it were a table.** Quote it;
do not model it. Saying "EO 14336 gives us the stockpile dataset" is the single
easiest thing here for a judge to falsify — the honest line is "EO 14336 is the
mandate; this is what it would need."
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE.parent / "cache" / "eo14336.json"
PINNED = HERE.parent.parent / "web" / "data" / "eo14336.citation.json"

API_URL = "https://www.federalregister.gov/api/v1/documents/2025-15823.json"
WHITEHOUSE_URL = ("https://www.whitehouse.gov/presidential-actions/2025/08/"
                  "ensuring-american-pharmaceutical-supply-chain-resilience-by-filling-"
                  "the-strategic-active-pharmaceutical-ingredients-reserve/")

EXPECTED = {
    "document_number": "2025-15823",
    "citation": "90 FR 40223",
    "executive_order_number": 14336,
    "signing_date": "2025-08-13",
    "publication_date": "2025-08-19",
}


def fetch() -> dict:
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(
            API_URL, headers={"User-Agent": "Mozilla/5.0 (CHOKEPOINT/DNHacks research)"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            CACHE.write_bytes(resp.read())
    return json.loads(CACHE.read_text())


def main() -> int:
    doc = fetch()
    print("EO 14336 (SAPIR) — Federal Register metadata")

    problems = []
    for key, want in EXPECTED.items():
        got = doc.get(key)
        if str(got) != str(want):
            problems.append(f"{key}: got {got!r}, expected {want!r}")
        print(f"  {key:<26} {got}")

    if problems:
        sys.exit("FAIL: EO 14336 metadata does not match what we cite:\n  "
                 + "\n  ".join(problems))

    year = str(doc.get("publication_date", ""))[:4]
    if year != "2025":
        sys.exit(f"FAIL: published {year}, not 2025. Several brain files had this "
                 f"wrong; do not reintroduce it.")
    print("  asserted: August 2025, not 2026")

    citation = {
        "document_number": doc["document_number"],
        "citation": doc["citation"],
        "executive_order_number": doc["executive_order_number"],
        "title": doc.get("title"),
        "signing_date": doc["signing_date"],
        "publication_date": doc["publication_date"],
        "volume": doc.get("volume"),
        "start_page": doc.get("start_page"),
        "end_page": doc.get("end_page"),
        "html_url": doc.get("html_url"),
        "raw_text_url": doc.get("raw_text_url"),
        "primary_source": WHITEHOUSE_URL,
        "what_it_is": "A mandate and a citation, not a dataset. Four sections of "
                      "policy text; nothing in the graph keys off it.",
        "say_this": "EO 14336 is the mandate; this is what it would need.",
        "not_this": "EO 14336 gives us the stockpile dataset.",
    }
    PINNED.parent.mkdir(parents=True, exist_ok=True)
    PINNED.write_text(json.dumps(citation, indent=2, ensure_ascii=False) + "\n")

    print(f"\n  pinned to {PINNED.relative_to(HERE.parent.parent)}")
    print("  0 nodes, 0 edges — deliberately. It is a citation, not a feed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
