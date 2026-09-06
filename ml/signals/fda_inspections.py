"""FDA Inspection Classification — an OAI on a manufacturing facility.

An **OAI** (Official Action Indicated) means FDA found significant objectionable
conditions at that site. It is facility-level and names foreign establishments,
which is rare in public pharma data.

❗ This is a CONFIRMING signal, not a leading one — classifications post months
after the inspection ends. That is exactly why `cascade_rules.py` treats it as a
STATE ("is this facility currently OAI?") rather than an EVENT inside a 90-day
window: a recency window can almost never catch one.

Anchors this feed must produce:
    Aurobindo Pharma Limited        FEI 3004446312  OAI 2025-09-05
    Centrient Pharmaceuticals India FEI 3004497364  OAI 2026-01-27
"""

from __future__ import annotations

import csv
import json
import re

from .common import LoaderError, Signal, cache_dir, fetch, iso, require
from .qlik import WebSocket

APP_TXT = "https://datadashboard.fda.gov/content/Apps/app.txt"
WS = "wss://datadashboard.fda.gov/hdr/app/{app_id}"

FIELDS = ["[Inspection ID]", "[FEI Number]", "[Legal Name]", "[City Name]",
          "[Country Name]", "[Street Address Line 1]", "[Inspection End Date]",
          "[Classification Code]", "[Product Type]", "[Center]",
          "[Project Area]", "[Posted Citations]"]

#: Selections applied to the session BEFORE paging. Order matters: selections are
#: session-wide, so they must precede the object we page.
SELECTIONS = [("Country Code", ["CN", "IN"]),
              ("Product Type", ["Drugs"]),
              ("Classification Code", ["OAI"])]

PAGE_ROWS = 700          # 700 x 12 = 8,400 cells, under the 10,000-cell limit


def _app_id() -> str:
    """Read the live app id. Needs a browser UA — this started 403ing recently."""
    txt = fetch(APP_TXT, cache_dir("fda-inspections") / "app.txt", timeout=30).decode()
    m = re.search(r"^prod\.id\s*=\s*(\S+)", txt, re.M)
    if not m:
        raise LoaderError(f"could not find prod.id in app.txt:\n{txt[:300]}")
    return m.group(1).strip()


def _pull_rows() -> list[dict]:
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
                "qInitialDataFetch": [{"qTop": 0, "qLeft": 0, "qHeight": 1, "qWidth": len(FIELDS)}],
            }}])["qReturn"]["qHandle"]

        total = ws.rpc("GetLayout", obj, [])["qLayout"]["qHyperCube"]["qSize"]["qcy"]
        if total == 0:
            raise LoaderError("selection returned 0 rows — the filter failed, "
                              "the world did not suddenly become clean")

        rows, top = [], 0
        while top < total:
            pages = ws.rpc("GetHyperCubeData", obj, ["/qHyperCubeDef", [
                {"qTop": top, "qLeft": 0, "qHeight": PAGE_ROWS, "qWidth": len(FIELDS)}]])["qDataPages"]
            matrix = pages[0]["qMatrix"] if pages else []
            if not matrix:
                break
            for cells in matrix:
                rows.append({f.strip("[]"): c.get("qText", "") for f, c in zip(FIELDS, cells)})
            top += len(matrix)
        return rows
    finally:
        ws.close()


def load(*, refresh: bool = False) -> list[Signal]:
    cache = cache_dir("fda-inspections")
    pinned = cache / "inspections_cn_in_drugs_oai.csv"

    if refresh or not pinned.exists():
        rows = _pull_rows()
        if rows:
            with pinned.open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
    else:
        rows = list(csv.DictReader(pinned.open()))

    out = []
    for r in rows:
        fei = (r.get("FEI Number") or "").strip()
        if not fei:
            continue
        out.append(Signal(
            node_id=f"facility:fei:{fei}",
            kind="inspection_classification",
            severity="high",
            source="FDA Inspection Classification",
            observed_at=iso(r["Inspection End Date"], "%m/%d/%Y"),
            url="https://datadashboard.fda.gov/ora/cd/inspections.htm",
            payload={"classification": (r.get("Classification Code") or "").strip(),
                     "firm": (r.get("Legal Name") or "").strip(),
                     "city": (r.get("City Name") or "").strip(),
                     "country": (r.get("Country Name") or "").strip(),
                     "product_type": (r.get("Product Type") or "").strip(),
                     "project_area": (r.get("Project Area") or "").strip()},
        ))

    print(f"  {len(rows):,} CN/IN drug OAI rows -> {len(out):,} signals")
    return require(out, "fda_inspections", minimum=50)


if __name__ == "__main__":
    import sys
    sig = load(refresh="--refresh" in sys.argv)
    print(f"\nanchors:")
    for fei in ("3004446312", "3004497364"):
        hits = [s for s in sig if s.node_id.endswith(fei)]
        tag = "OK " if hits else "MISSING"
        for s in sorted(hits, key=lambda x: x.observed_at, reverse=True):
            print(f"  [{tag}] {s.observed_at}  {s.node_id}  {s.payload['firm'][:44]}")
        if not hits:
            print(f"  [MISSING] FEI {fei}")
