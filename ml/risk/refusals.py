"""Step 2 — OASIS import refusals, UNFILTERED.

    python3 -m ml.risk.refusals

`ml/signals/oasis.py` keeps only chokepoint countries (CN/IN) or rows touching a
tracked antibiotic — correct for the demo feed, far too narrow for a model that
needs to learn what a normal plant's border record looks like.

This keeps every **drug-industry** row (product code industries 55–66), all
countries, all ingredients, and preserves the one distinction that matters:

  * **manufacturing** charges — 27 `DRUG GMPS` (adulteration) and 3280
    `FRNMFGREG` (unregistered foreign manufacturer). Real quality evidence.
  * **paperwork** charges — 118 `NOT LISTED`, 472 `NO ENGLISH`. Administrative.

Those are not the same event and must not share a label. A paperwork refusal is a
weak *leading* feature (a plant losing control of its filings), never a positive.

One shipment is one event: entry lines are collapsed on
`(fei, date, charge, product)`, because a 66-line shipment is one refusal, not 66.
"""

from __future__ import annotations

import csv
import io
import sys
import zipfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ml.risk.inspections import fei  # noqa: E402
from ml.signals.common import cache_dir, fetch  # noqa: E402

#: The "2024-present" file the demo loader uses covers ~2.5 years. That is fine
#: for a live signal feed and useless for a model: at a 2023 cutoff every refusal
#: feature is identically zero, so three of the ten features are dead and the
#: model silently trains on seven. FDA publishes archives; pull them too.
ZIP_URLS = [
    "https://www.accessdata.fda.gov/scripts/importrefusals/downloads/Import_Refusal_2024-present.zip",
    "https://www.accessdata.fda.gov/scripts/importrefusals/downloads/Import_Refusal_2019-2023.zip",
    "https://www.accessdata.fda.gov/scripts/importrefusals/downloads/Import_Refusal_2014-2018.zip",
]
DRUG_INDUSTRIES = {str(i) for i in range(55, 67)}
MFG_CHARGES = {"27": "cGMP adulteration", "3280": "unregistered foreign manufacturer"}
PAPER_CHARGES = {"118": "not listed with FDA", "472": "labeling not in English"}
OUT = "refusals.csv"


def load(refresh: bool = False) -> list[dict]:
    dest = cache_dir("risk") / OUT
    if dest.exists() and not refresh:
        return list(csv.DictReader(dest.open()))

    parts = []
    for url in ZIP_URLS:
        blob = cache_dir("risk") / url.rsplit("/", 1)[1]
        if not blob.exists():
            print(f"  fetching {blob.name}")
            fetch(url, blob, timeout=300)
        with zipfile.ZipFile(blob) as z:
            entry = next((n for n in z.namelist()
                          if n.upper().startswith("REFUSAL_ENTRY")), None)
            if not entry:
                print(f"  ! {blob.name}: no REFUSAL_ENTRY member, skipped")
                continue
            parts.append(z.read(entry).decode("utf-8", errors="replace"))

    merged: dict[tuple, dict] = {}
    stats = Counter()
    rows_iter = (row for raw in parts for row in csv.DictReader(io.StringIO(raw)))
    for r in rows_iter:
        stats["total"] += 1
        if (r.get("PRODUCT_CODE") or "").strip()[:2] not in DRUG_INDUSTRIES:
            continue
        stats["drug"] += 1
        f = fei(r.get("MFG_FIRM_FEI_NUM"))
        if not f:
            stats["no_fei"] += 1
            continue
        charges = {c.strip() for c in (r.get("REFUSAL_CHARGES") or "").split(",")}
        mfg = charges & set(MFG_CHARGES)
        paper = charges & set(PAPER_CHARGES)
        if mfg:
            code, kind = sorted(mfg)[0], "mfg"
        elif paper:
            code, kind = sorted(paper)[0], "paperwork"
        else:
            stats["other_charge"] += 1
            continue
        key = (f, r.get("REFUSAL_DATE", "").strip(), code,
               (r.get("PRODUCT_CODE") or "").strip())
        if key in merged:
            merged[key]["entry_lines"] = str(int(merged[key]["entry_lines"]) + 1)
            continue
        merged[key] = {
            "fei": f, "date": r["REFUSAL_DATE"].strip(), "kind": kind,
            "charge": code, "charge_label": (MFG_CHARGES | PAPER_CHARGES)[code],
            "country": (r.get("ISO_CNTRY_CODE") or "").strip().upper(),
            "firm": (r.get("LGL_NAME") or "").strip(),
            "product": (r.get("PRDCT_CODE_DESC_TEXT") or "").strip(),
            "entry_lines": "1",
        }

    out = list(merged.values())
    print(f"  rows {stats['total']:,} → drug {stats['drug']:,} → "
          f"{len(out):,} events after collapsing entry lines "
          f"({stats['no_fei']:,} had no FEI)")
    with dest.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    return out


def main() -> int:
    import json
    rows = load(refresh="--refresh" in sys.argv)
    k = Counter(r["kind"] for r in rows)
    print(f"\n  {len(rows):,} events · {len({r['fei'] for r in rows}):,} distinct FEI")
    print(f"  kinds: {dict(k)}")
    print(f"  countries: {len({r['country'] for r in rows if r['country']})}")

    # The demo feed must be a strict subset of this wider pull, or one of the two
    # loaders is dropping rows the other keeps.
    sig = Path(__file__).resolve().parents[2] / "web" / "data" / "signals.json"
    if sig.exists():
        want = {(r["node_id"].rsplit(":", 1)[1], r["observed_at"])
                for r in json.loads(sig.read_text())
                if r["kind"].startswith("import_refusal")}
        from datetime import datetime
        have = set()
        for r in rows:
            try:
                d = datetime.strptime(r["date"], "%d-%b-%y").date().isoformat()
            except ValueError:
                continue
            have.add((r["fei"], d))
        missing = want - have
        print(f"  [{'OK ' if not missing else 'WARN'}] signals.json refusals ⊆ this file "
              f"({len(want)} wanted, {len(missing)} missing)")
        for m in sorted(missing)[:3]:
            print(f"       missing {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
