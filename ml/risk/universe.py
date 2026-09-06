"""Step 3 — the universe: every plant the model is allowed to score.

    python3 -m ml.risk.universe [--cutoff 2023-01-01]

This is the step that prevents the whole exercise from being circular.

`signals.json` contains 853 facilities and **every one of them is there because
something went wrong**. Train on that and the model learns "plants I have heard
of are risky", which is true by construction and worth nothing. It would score
1.0 on its own data and fail on the first clean plant it met.

So the universe at a cutoff is:

    DECRS establishments flagged `API MANUFACTURE`
  ∪ every FEI with any **Drugs** inspection (NAI, VAI or OAI) ending ≤ cutoff

The second half is what supplies the negatives: ~18,000 facilities the FDA has
inspected and mostly found fine. Country comes from DECRS first (it is the
registration of record) and from the inspection row second.
"""

from __future__ import annotations

import re
import sys
import zipfile
from collections import Counter
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ml.risk.inspections import fei, load as load_inspections  # noqa: E402
from ml.signals.common import cache_dir, fetch  # noqa: E402

DECRS_URL = "https://www.accessdata.fda.gov/cder/drls_reg.zip"


def parse_date(v: str) -> date | None:
    """FDA dates arrive in several shapes and a bad one must not be guessed at."""
    for fmt in ("%m/%d/%Y", "%d-%b-%y", "%Y-%m-%d"):
        try:
            return datetime.strptime((v or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def decrs() -> dict[str, dict]:
    """FEI -> {country, api, firm} from the establishment register."""
    blob = cache_dir("decrs") / "drls_reg.zip"
    if not blob.exists():
        fetch(DECRS_URL, blob, timeout=240)
    with zipfile.ZipFile(blob) as z:
        lines = z.read("drls_reg.txt").decode("utf-8", errors="replace").splitlines()
    hdr = [h.strip() for h in lines[0].split("\t")]
    out: dict[str, dict] = {}
    for line in lines[1:]:
        r = dict(zip(hdr, [c.strip() for c in line.split("\t")]))
        f = fei(r.get("FEI_NUMBER"))
        if not f:
            continue
        iso = re.findall(r"\(([A-Z]{3})\)", r.get("ADDRESS") or "")
        rec = out.setdefault(f, {"country": None, "api": False, "firm": r.get("FIRM_NAME")})
        rec["country"] = rec["country"] or (iso[-1] if iso else None)
        if "API MANUFACTURE" in (r.get("OPERATIONS") or ""):
            rec["api"] = True
    return out


#: ISO3 (DECRS) -> ISO2 (inspection rows). Only the codes our data actually uses.
_ISO3_TO_2 = {"CHN": "CN", "IND": "IN", "USA": "US", "DEU": "DE", "ITA": "IT",
              "JPN": "JP", "KOR": "KR", "ESP": "ES", "AUT": "AT", "CHE": "CH",
              "GBR": "GB", "FRA": "FR", "IRL": "IE", "ISR": "IL", "CAN": "CA",
              "MEX": "MX", "BRA": "BR", "TWN": "TW", "SGP": "SG", "NLD": "NL"}


#: A plant FDA has not looked at in this long is outside the population the
#: model is about. See MODEL_NAMES in features.py for why.
ACTIVE_MONTHS = 60


def universe(cutoff: date, active_only: bool = True) -> dict[str, dict]:
    """Every FEI scoreable at `cutoff`, with its country and how it qualified.

    `active_only` (the default) keeps only plants inspected within
    `ACTIVE_MONTHS`. That is the honest population for this question: the label
    is "FDA recorded trouble", so a plant FDA never visits cannot produce one,
    and including it teaches the model to predict inspection schedules. It also
    halves the universe (17.3k -> 7.2k) while RAISING AUC, because the rows it
    removes were easy negatives that flattered the score.
    """
    reg = decrs()
    insp = load_inspections()

    seen_by_insp: dict[str, str] = {}
    for r in insp:
        d = parse_date(r["end_date"])
        if d and d <= cutoff and r["fei"]:
            seen_by_insp.setdefault(r["fei"], r["country_code"])

    recent: set[str] = set()
    if active_only:
        floor = date(cutoff.year - ACTIVE_MONTHS // 12, cutoff.month, cutoff.day)
        for r in insp:
            d = parse_date(r["end_date"])
            if d and floor <= d <= cutoff:
                recent.add(r["fei"])

    out: dict[str, dict] = {}
    for f, rec in reg.items():
        if active_only and f not in recent:
            continue
        if rec["api"]:
            out[f] = {"fei": f, "country": _ISO3_TO_2.get(rec["country"] or "", ""),
                      "firm": rec["firm"], "source": "decrs-api"}
    for f, cc in seen_by_insp.items():
        if active_only and f not in recent:
            continue
        if f in out:
            out[f]["country"] = out[f]["country"] or cc
        else:
            out[f] = {"fei": f, "country": cc,
                      "firm": reg.get(f, {}).get("firm") or "", "source": "inspected"}
    return out


def main() -> int:
    cut = date(2023, 1, 1)
    if "--cutoff" in sys.argv:
        cut = date.fromisoformat(sys.argv[sys.argv.index("--cutoff") + 1])
    u = universe(cut)
    src = Counter(v["source"] for v in u.values())
    cc = Counter(v["country"] for v in u.values() if v["country"])
    print(f"UNIVERSE at {cut}\n")
    print(f"  {len(u):,} facilities  {dict(src)}")
    print(f"  top countries: {dict(cc.most_common(6))}")
    print(f"  no country resolved: {sum(1 for v in u.values() if not v['country']):,}")

    import json
    rr = Path(__file__).resolve().parents[2] / "web" / "data" / "reroute.json"
    if rr.exists():
        want, miss = set(), []
        # The route-ui redesign renamed `nodes` -> `precursors` and `alternates`
        # -> `holders`. Read both so this check keeps testing something after a
        # schema change instead of silently passing on an empty set.
        doc = json.loads(rr.read_text())
        groups = doc.get("precursors") or doc.get("nodes") or {}
        for p in (groups.values() if isinstance(groups, dict) else groups):
            for a in p.get("holders", p.get("alternates", [])):
                for f in a.get("feis", []):
                    want.add(fei(f))
        miss = [f for f in want if f and f not in u]
        print(f"  [{'OK ' if not miss else 'WARN'}] every AEGIS plant is scoreable "
              f"({len(want)} FEIs, {len(miss)} missing)")
    ok = 5000 <= len(u) <= 25000
    print(f"  [{'OK ' if ok else 'CHECK'}] size {len(u):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
