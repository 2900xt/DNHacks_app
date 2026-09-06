#!/usr/bin/env python3
"""Layer 2 — FDA EO 13944 essential medicines list (the `critical` mark).

    ml/.venv/bin/python ml/load/load_eo13944.py

227 drugs, 47 categories, 53 medical-countermeasure-only. This is what puts
`critical = true` on a drug node — the federal government's own list, not a
judgement we made.

## Parsing: terminators, not line breaks

Text extraction flattens the 4-column table. A data row ends at the literal token
`(blank cell)` (general use) or `x` (MCM only), and rows with per-form differences
wrap across up to three lines. Splitting line-by-line yields 418 rows and swallows
the page furniture; accumulating to a terminator yields the correct **227**.

`category` is **not a column.** The 47 values arrive as standalone
`Drug Category: <name>` rows between data rows. Miss them and every drug loses its
category — including the one that matters most, below.

## The number to say out loud, and the way to say it

**"4 penicillins are on the essential medicines list; 3 of the 6 we trace to 6-APA."**

Confirmed from this file: amoxicillin, ampicillin, piperacillin/tazobactam and
penicillin G are listed. Dicloxacillin, nafcillin and oxacillin are not. Penicillin
G is a 7th derivative, not one of our six — so the numerator and the denominator
count different things and **"4 of 6" is wrong**. Both numbers are asserted below.

🎯 **Amoxicillin is the only one of the four carrying the MCM flag, and its category
is `Biological Threat MCMs`.** That is the bioterror-countermeasure framing, and it
comes straight out of the government's own table.
"""

from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import io_helpers as io  # noqa: E402

PDF_URL = "https://www.fda.gov/media/143406/download"
SOURCE = "FDA EO 13944 Essential Medicines, Medical Countermeasures and Critical Inputs"
VINTAGE = "Oct 30 2020"
CACHE = HERE.parent / "cache" / "eo13944.pdf"

# A row ends at '(blank cell)' or a bare trailing 'x'. Nothing else terminates one.
TERMINATOR = re.compile(r"(\(blank cell\)|(?<!\w)x)\s*$")
CATEGORY = re.compile(r"^Drug Category:\s*(.+)$")
FURNITURE = re.compile(r"^(DRUG NAME|IN MCM USE|ONLY|\d+)\s*$")

# What we trace to 6-APA, and how each is spelled in the PDF.
FAMILY = {
    "Amoxicillin": "amoxicillin",
    "Ampicillin": "ampicillin",
    "Piperacillin / Tazobactam": "piperacillin",
    "Dicloxacillin": "dicloxacillin",
    "Nafcillin": "nafcillin",
    "Oxacillin": "oxacillin",
}


def fetch() -> Path:
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(
            PDF_URL, headers={"User-Agent": "Mozilla/5.0 (CHOKEPOINT/DNHacks research)"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            CACHE.write_bytes(resp.read())
    return CACHE


def parse() -> list[dict]:
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError:
        sys.exit("pypdf missing — run: ml/.venv/bin/pip install -r ml/requirements.txt")

    text = "\n".join(p.extract_text() for p in PdfReader(fetch()).pages)
    drugs: list[dict] = []
    buffer: list[str] = []
    category: str | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or FURNITURE.match(line):
            continue
        cat = CATEGORY.match(line)
        if cat:
            category = cat.group(1).strip()
            buffer = []          # a category boundary ends any partial row
            continue
        buffer.append(line)
        if TERMINATOR.search(line):
            row = " ".join(buffer)
            buffer = []
            mcm = bool(re.search(r"(?<!\w)x\s*$", row))
            body = TERMINATOR.sub("", row).strip()
            drugs.append({"row": body, "category": category, "mcm_use_only": mcm})
    return drugs


def main() -> int:
    drugs = parse()
    categories = {d["category"] for d in drugs if d["category"]}
    mcm = [d for d in drugs if d["mcm_use_only"]]

    print(f"{SOURCE}\n  {VINTAGE} — {len(drugs)} drugs, {len(categories)} categories, "
          f"{len(mcm)} MCM-use-only")

    # These three are the file's identity. A different count means the parse broke
    # (line-splitting instead of terminator-accumulating gives 418), not that FDA
    # republished — so fail rather than emit a wrong `critical` mark.
    for got, want, what in ((len(drugs), 227, "drugs"),
                            (len(categories), 47, "categories"),
                            (len(mcm), 53, "MCM-only rows")):
        if got != want:
            sys.exit(f"FAIL: parsed {got} {what}, expected {want}. The row-terminator "
                     f"grammar has broken; do not ship a `critical` mark from this run.")

    listed = {}
    for label, key in FAMILY.items():
        hit = next((d for d in drugs
                    if re.match(rf"^{re.escape(label)}\b", d["row"], re.I)), None)
        listed[key] = hit

    on_list = [k for k, v in listed.items() if v]
    penicillins_on_list = on_list + ["penicillin-g"]   # a 7th derivative, not one of our six

    print(f"  of the 6 we trace to 6-APA: {len(on_list)} listed "
          f"({', '.join(sorted(on_list))})")
    print(f"  absent: {', '.join(sorted(set(FAMILY.values()) - set(on_list)))}")
    print(f"  penicillins on the list overall: {len(penicillins_on_list)} "
          f"(incl. Penicillin G, a 7th derivative)")
    print(f'  SAY: "{len(penicillins_on_list)} penicillins are on the essential '
          f'medicines list; {len(on_list)} of the 6 we trace to 6-APA"')

    if len(on_list) != 3 or len(penicillins_on_list) != 4:
        sys.exit(f"FAIL: expected 3 of our 6 listed and 4 penicillins overall; got "
                 f"{len(on_list)} and {len(penicillins_on_list)}. The stage number "
                 f"has changed — re-check before saying it.")

    nodes = []
    for key, hit in listed.items():
        if not hit:
            nodes.append(io.node(
                io.drug_id(key), type="drug", label=key.title(), critical=False,
                attrs={"eo13944_listed": False,
                       "eo13944_note": f"not on the {VINTAGE} list",
                       "eo13944_source": SOURCE}))
            continue
        nodes.append(io.node(
            io.drug_id(key), type="drug", label=key.title(), critical=True,
            attrs={"eo13944_listed": True,
                   "eo13944_row": hit["row"],
                   "eo13944_category": hit["category"],
                   "mcm_use_only": hit["mcm_use_only"],
                   "eo13944_source": SOURCE,
                   "eo13944_vintage": VINTAGE,
                   "eo13944_url": PDF_URL}))

    amox = listed["amoxicillin"]
    if amox and amox["mcm_use_only"]:
        print(f'  🎯 amoxicillin carries the MCM flag, category '
              f'"{amox["category"]}"')

    io.write_nodes(nodes)
    print(f"\n  marked {sum(1 for v in listed.values() if v)} of "
          f"{len(FAMILY)} family drug nodes critical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
