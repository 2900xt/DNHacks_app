"""Step 1 — FDA inspection history, UNFILTERED.

    python3 -m ml.risk.inspections          # cached
    python3 -m ml.risk.inspections --refresh

`ml/signals/fda_inspections.py` pulls the same source but filtered to
`Country CN/IN · Product Drugs · Classification OAI` — 479 rows. That is the
right filter for the demo signal feed and the wrong one for a model:

**every facility in `signals.json` is there because something went wrong with it.**
A model trained on that file has no clean plants to learn from, so it cannot
learn what "clean" looks like. It would score every plant it has ever heard of as
high risk and be right by construction.

So this pulls **Drugs, all countries, all classifications** — ~39,900 rows,
roughly NAI 30k / VAI 7k / OAI 3k. The NAI and VAI rows the signal loader discards
are exactly the negatives the model needs.

Cached separately under `data/cache/risk/` so nothing here can disturb the
demo's `signals.json`.

⚠️ The Qlik hypercube de-duplicates identical dimension tuples, so this lands a
few rows short of the dashboard's headline count. Documented in
`project/datasets/fda-inspection-classification.md`; not a bug.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ml.signals.common import LoaderError, cache_dir, fetch  # noqa: E402
from ml.signals.qlik import WebSocket  # noqa: E402

APP_TXT = "https://datadashboard.fda.gov/content/Apps/app.txt"
WS = "wss://datadashboard.fda.gov/hdr/app/{app_id}"

FIELDS = ["[FEI Number]", "[Legal Name]", "[Country Code]", "[Country Name]",
          "[Inspection End Date]", "[Classification Code]", "[Product Type]",
          "[Project Area]"]

#: Drugs only. NOT filtered by country or classification — see the module docstring.
SELECTIONS = [("Product Type", ["Drugs"])]

PAGE_ROWS = 1200          # 1200 x 8 = 9,600 cells, under the engine's 10,000 cap
OUT = "inspections.csv"


def fei(v) -> str:
    """Canonical FEI.

    DECRS mixes 7- and 10-character FEIs with leading zeros; the dashboard emits
    10 characters without them. Comparing raw strings silently fails to join, and
    the failure looks like "this plant has no history" rather than like an error.
    """
    s = re.sub(r"\D", "", str(v or ""))
    return str(int(s)) if s else ""


def _app_id() -> str:
    txt = fetch(APP_TXT, cache_dir("risk") / "app.txt", timeout=30).decode()
    m = re.search(r"^prod\.id\s*=\s*(\S+)", txt, re.M)
    if not m:
        raise LoaderError(f"no prod.id in app.txt:\n{txt[:300]}")
    return m.group(1).strip()


def pull() -> list[dict]:
    app_id = _app_id()
    ws = WebSocket(WS.format(app_id=app_id))
    try:
        doc = ws.rpc("OpenDoc", -1, [app_id, "", "", "", False])["qReturn"]["qHandle"]
        for field, values in SELECTIONS:
            fh = ws.rpc("GetField", doc, [field])["qReturn"]["qHandle"]
            ws.rpc("SelectValues", fh, [[{"qText": v} for v in values], False, False])

        obj = ws.rpc("CreateSessionObject", doc, [{
            "qInfo": {"qType": "table"},
            "qHyperCubeDef": {
                "qDimensions": [{"qDef": {"qFieldDefs": [f]}} for f in FIELDS],
                "qMeasures": [],
                "qInitialDataFetch": [{"qTop": 0, "qLeft": 0, "qHeight": 1,
                                       "qWidth": len(FIELDS)}],
            }}])["qReturn"]["qHandle"]

        total = ws.rpc("GetLayout", obj, [])["qLayout"]["qHyperCube"]["qSize"]["qcy"]
        if total == 0:
            raise LoaderError("selection returned 0 rows — the filter failed, the "
                              "FDA did not stop inspecting drug plants")
        print(f"  engine reports {total:,} Drugs inspection rows")

        rows, top = [], 0
        while top < total:
            pages = ws.rpc("GetHyperCubeData", obj, ["/qHyperCubeDef", [
                {"qTop": top, "qLeft": 0, "qHeight": PAGE_ROWS,
                 "qWidth": len(FIELDS)}]])["qDataPages"]
            matrix = pages[0]["qMatrix"] if pages else []
            if not matrix:
                break
            for cells in matrix:
                r = {f.strip("[]"): c.get("qText", "") for f, c in zip(FIELDS, cells)}
                rows.append(r)
            top += len(matrix)
            if top % 6000 < PAGE_ROWS:
                print(f"    {top:,}/{total:,}")
        return rows
    finally:
        ws.close()


def load(refresh: bool = False) -> list[dict]:
    dest = cache_dir("risk") / OUT
    if dest.exists() and not refresh:
        return list(csv.DictReader(dest.open()))

    raw = pull()
    out = []
    for r in raw:
        f = fei(r.get("FEI Number"))
        if not f:
            continue
        out.append({
            "fei": f,
            "firm": (r.get("Legal Name") or "").strip(),
            "country_code": (r.get("Country Code") or "").strip().upper(),
            "country_name": (r.get("Country Name") or "").strip(),
            "end_date": (r.get("Inspection End Date") or "").strip(),
            "classification": (r.get("Classification Code") or "").strip().upper(),
            "project_area": (r.get("Project Area") or "").strip(),
        })
    with dest.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    return out


def main() -> int:
    import collections
    rows = load(refresh="--refresh" in sys.argv)
    c = collections.Counter(r["classification"] for r in rows)
    print(f"\n  {len(rows):,} rows · {len({r['fei'] for r in rows}):,} distinct FEI")
    print(f"  classifications: {dict(c.most_common())}")
    dates = sorted(r["end_date"] for r in rows if r["end_date"])
    print(f"  dates: {dates[0]} → {dates[-1]}")
    print(f"  countries: {len({r['country_code'] for r in rows if r['country_code']})}")

    # The anchors, which must survive an unfiltered pull unchanged.
    for f, name, want in (("3004446312", "Aurobindo", "09/05/2025"),
                          ("3004497364", "Centrient", "01/27/2026")):
        hits = [r for r in rows if r["fei"] == f and r["classification"] == "OAI"]
        ok = any(h["end_date"] == want for h in hits)
        print(f"  [{'OK ' if ok else 'FAIL'}] {name} FEI {f}: {len(hits)} OAI, expected {want}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
