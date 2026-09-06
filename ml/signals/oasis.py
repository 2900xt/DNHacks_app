"""OASIS import refusals — a shipment stopped at the US border.

Bulk zip, no key. The Data Dashboard REST API needs a key FDA issues by email
with no SLA, so it is not an option; the zip is open and is the path.

⚠️ Most drug refusals are noise. 13,502 of 16,540 drug rows carry charge
`UNAPPROVED-75` — grey-market and personal imports, not supply-chain events. The
real signal is charge **27 (cGMP adulteration, 660 drug rows)** and **3280
(unregistered foreign manufacturer, 2,905)**. We keep those and drop the rest,
or the feed drowns the graph.

Anchor this feed must produce:
    CSPC Zhongnuo, FEI 3003196232, AMOXICILLIN TRIHYDRATE, refused 24-Jul-2026
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections import Counter

from .common import Signal, cache_dir, fetch, iso, require

ZIP_URL = ("https://www.accessdata.fda.gov/scripts/importrefusals/downloads/"
           "Import_Refusal_2024-present.zip")

#: Industry codes 55-66 are drugs; 56 is antibiotics specifically.
DRUG_INDUSTRIES = {str(i) for i in range(55, 67)}

#: Charge codes that indicate a real manufacturing/supply problem.
#: Deliberately excludes UNAPPROVED-75, which is 82% of drug rows and is
#: grey-market imports rather than a chokepoint signal.
SIGNAL_CHARGES = {"27": ("cGMP adulteration", "high"),
                  "3280": ("unregistered foreign manufacturer", "medium")}

#: ❗ Paperwork refusals, NOT manufacturing failures. Emitted only when the row
#: touches a tracked ingredient, because 118 alone is 4,899 drug rows of noise.
#: This is how the CSPC Zhongnuo anchor survives without being oversold: its
#: charges are 118 + 472, i.e. "not listed with FDA" and "labeling not in
#: English" - a compliance stop, not a quality failure. Do NOT narrate it as a
#: plant problem. The stronger amoxicillin anchor is Sun Pharma, charge 27.
PAPERWORK_CHARGES = {"118": ("not listed with FDA", "low"),
                     "472": ("labeling not in English", "low")}

#: Ingredients the graph cares about. Substring matching on the product
#: description is safe here (it is a controlled FDA vocabulary), EXCEPT for
#: oxacillin - see below.
INGREDIENTS = ["AMOXICILLIN", "AMPICILLIN", "PIPERACILLIN", "PENICILLIN",
               "AZITHROMYCIN", "CEPHALOSPORIN", "6-APA"]


def _industry(product_code: str) -> str:
    return (product_code or "").strip()[:2]


def _ingredient(desc: str) -> str | None:
    d = (desc or "").upper()
    for ing in INGREDIENTS:
        if ing in d:
            return ing
    # OXACILLIN is a substring of CLOXACILLIN, DICLOXACILLIN and FLOXACILLIN.
    # Naive matching returns 7 rows; real oxacillin refusals are 0. Require a
    # word boundary rather than a substring.
    import re
    if re.search(r"\bOXACILLIN\b", d):
        return "OXACILLIN"
    return None


def load() -> list[Signal]:
    cache = cache_dir("oasis")
    blob = cache / "Import_Refusal_2024-present.zip"
    if not blob.exists():
        fetch(ZIP_URL, blob, timeout=180)

    with zipfile.ZipFile(blob) as z:
        entry = next(n for n in z.namelist() if n.upper().startswith("REFUSAL_ENTRY"))
        raw = z.read(entry).decode("utf-8", errors="replace")

    rows = list(csv.DictReader(io.StringIO(raw)))
    stats = Counter()
    out: list[Signal] = []

    for r in rows:
        stats["total"] += 1
        if _industry(r.get("PRODUCT_CODE", "")) not in DRUG_INDUSTRIES:
            continue
        stats["drug"] += 1

        charges = {c.strip() for c in (r.get("REFUSAL_CHARGES") or "").split(",")}
        ingredient = _ingredient(r.get("PRDCT_CODE_DESC_TEXT", ""))

        hit = charges & set(SIGNAL_CHARGES)
        paper = charges & set(PAPERWORK_CHARGES)
        if hit:
            code = sorted(hit)[0]
            label, severity = SIGNAL_CHARGES[code]
            kind = "import_refusal"
            stats["signal"] += 1
        elif paper and ingredient:
            code = sorted(paper)[0]
            label, severity = PAPERWORK_CHARGES[code]
            kind = "import_refusal_paperwork"
            stats["paperwork"] += 1
        else:
            continue

        fei = (r.get("MFG_FIRM_FEI_NUM") or "").strip()
        if not fei:
            stats["no_fei"] += 1
            continue

        out.append(Signal(
            node_id=f"facility:fei:{fei}",
            kind=kind,
            severity=severity,
            source="OASIS import refusals",
            observed_at=iso(r["REFUSAL_DATE"], "%d-%b-%y"),   # e.g. 24-Jul-26
            url="https://www.accessdata.fda.gov/scripts/importrefusals/",
            payload={"firm": (r.get("LGL_NAME") or "").strip(),
                     "country": (r.get("ISO_CNTRY_CODE") or "").strip(),
                     "product": (r.get("PRDCT_CODE_DESC_TEXT") or "").strip(),
                     "product_code": (r.get("PRODUCT_CODE") or "").strip(),
                     "charge": code, "charge_label": label,
                     "ingredient": ingredient},
        ))

    print(f"  rows {stats['total']:,} -> drug {stats['drug']:,} -> "
          f"supply-chain {stats['signal']:,} + ingredient-gated paperwork "
          f"{stats['paperwork']:,} -> emitted {len(out):,}")
    return require(out, "oasis", minimum=100)


if __name__ == "__main__":
    sig = load()
    anchors = [s for s in sig if s.payload.get("ingredient") == "AMOXICILLIN"]
    print(f"\n{len(anchors)} amoxicillin refusals with a supply-chain charge:")
    for s in sorted(anchors, key=lambda x: x.observed_at, reverse=True)[:10]:
        print(f"  {s.observed_at}  {s.node_id:26s} {s.payload['country']:3s} "
              f"{s.payload['firm'][:38]:38s} charge {s.payload['charge']}")
