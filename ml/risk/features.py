"""Step 4 — features at a cutoff. Ten, and nothing that peeks past the line.

    python3 -m ml.risk.features [--cutoff 2023-01-01]

Every value is computed from rows dated **≤ cutoff**. The single most likely bug
in this whole feature is a value that quietly includes the future, so the
self-check asserts the one case we can eyeball: Aurobindo's OAI is dated
2025-09-05, and at a 2025-01-01 cutoff it must be **absent**.

Counts are `log1p`-transformed: the difference between 0 and 1 prior failures is
enormous, between 8 and 9 it is noise.
"""

from __future__ import annotations

import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ml.risk.inspections import load as load_inspections  # noqa: E402
from ml.risk.refusals import load as load_refusals  # noqa: E402
from ml.risk.universe import parse_date, universe  # noqa: E402

NAMES = ["oai_all", "oai_3y", "months_since_oai", "vai_3y", "insp_3y",
         "months_since_insp", "refusal_mfg_3y", "refusal_paper_3y",
         "refusal_trend", "country_cn", "country_in"]

#: What the MODEL is allowed to use. `insp_3y` and `months_since_insp` are
#: computed (the evidence lines need them - "last inspected five years ago") but
#: deliberately withheld from the fit.
#:
#: They measure INSPECTION CADENCE, not plant risk, and the label is "FDA
#: recorded trouble", so they leak the detector into the prediction: you cannot
#: fail an inspection that never happens. Measured at the 2024 cutoff, plants
#: inspected in the last 3 years have a 2.01% positive rate against 0.21% for
#: plants not seen in a decade - a 10x gap that is about FDA's schedule, not
#: about the plants.
#:
#: Left in, they also make the model unexplainable: `months_since_insp` fits at
#: -0.540 (longer since inspection = safer), which is true and useless, and
#: `insp_3y` flips sign between the univariate view (0.615) and the multivariate
#: fit (-0.408). The spec's rule is that every coefficient must be explainable in
#: one sentence; these are not.
#:
#: Dropping them costs nothing: AUC 0.814 vs 0.811 at the 2023 cutoff.
MODEL_NAMES = [n for n in NAMES if n not in ("insp_3y", "months_since_insp")]

CAP_MONTHS = 120.0


def _months(a: date, b: date) -> float:
    return (a.year - b.year) * 12 + (a.month - b.month) + (a.day - b.day) / 30.0


class History:
    """Every dated event per FEI, loaded once and sliced per cutoff."""

    def __init__(self) -> None:
        self.insp: dict[str, list[tuple[date, str]]] = defaultdict(list)
        self.refu: dict[str, list[tuple[date, str]]] = defaultdict(list)
        for r in load_inspections():
            d = parse_date(r["end_date"])
            if d and r["fei"]:
                self.insp[r["fei"]].append((d, r["classification"]))
        for r in load_refusals():
            d = parse_date(r["date"])
            if d and r["fei"]:
                self.refu[r["fei"]].append((d, r["kind"]))

    def features(self, fei: str, cutoff: date, country: str = "") -> dict[str, float]:
        y3 = date(cutoff.year - 3, cutoff.month, cutoff.day)
        y1 = date(cutoff.year - 1, cutoff.month, cutoff.day)
        y2 = date(cutoff.year - 2, cutoff.month, cutoff.day)

        insp = [(d, c) for d, c in self.insp.get(fei, ()) if d <= cutoff]
        refu = [(d, k) for d, k in self.refu.get(fei, ()) if d <= cutoff]

        oai = [d for d, c in insp if c == "OAI"]
        vai = [d for d, c in insp if c == "VAI"]
        mfg = [d for d, k in refu if k == "mfg"]
        paper = [d for d, k in refu if k == "paperwork"]

        return {
            "oai_all": math.log1p(len(oai)),
            "oai_3y": math.log1p(sum(1 for d in oai if d >= y3)),
            "months_since_oai": min(CAP_MONTHS, _months(cutoff, max(oai))) if oai else CAP_MONTHS,
            "vai_3y": math.log1p(sum(1 for d in vai if d >= y3)),
            "insp_3y": math.log1p(sum(1 for d, _ in insp if d >= y3)),
            "months_since_insp": (min(CAP_MONTHS, _months(cutoff, max(d for d, _ in insp)))
                                  if insp else CAP_MONTHS),
            "refusal_mfg_3y": math.log1p(sum(1 for d in mfg if d >= y3)),
            "refusal_paper_3y": math.log1p(sum(1 for d in paper if d >= y3)),
            # Direction, not level: a plant going from 1 refusal to 3 is a
            # different story from one going from 3 to 1, and the level features
            # above cannot tell them apart.
            "refusal_trend": float(sum(1 for d in mfg + paper if d >= y1)
                                   - sum(1 for d in mfg + paper if y2 <= d < y1)),
            "country_cn": 1.0 if country == "CN" else 0.0,
            "country_in": 1.0 if country == "IN" else 0.0,
        }


def feature_table(cutoff: date, hist: History | None = None):
    hist = hist or History()
    uni = universe(cutoff)
    feis = sorted(uni)
    rows = [hist.features(f, cutoff, uni[f]["country"]) for f in feis]
    return feis, rows, uni


def main() -> int:
    cut = date(2023, 1, 1)
    if "--cutoff" in sys.argv:
        cut = date.fromisoformat(sys.argv[sys.argv.index("--cutoff") + 1])
    hist = History()
    feis, rows, uni = feature_table(cut, hist)
    print(f"FEATURES at {cut}\n  {len(rows):,} rows x {len(NAMES)} features")

    nan = [i for i, r in enumerate(rows) if any(v != v for v in r.values())]
    print(f"  [{'OK ' if not nan else 'FAIL'}] no NaN ({len(nan)} bad rows)")

    # Leakage: Aurobindo's only OAI is 2025-09-05.
    a = "3004446312"
    before = hist.features(a, date(2025, 1, 1))
    after = hist.features(a, date(2026, 1, 1))
    ok = before["oai_all"] == 0.0 and after["oai_all"] > 0.0
    print(f"  [{'OK ' if ok else 'FAIL'}] no leakage — Aurobindo OAI (2025-09-05) "
          f"absent at 2025-01-01 (oai_all={before['oai_all']:.2f}) and present at "
          f"2026-01-01 (oai_all={after['oai_all']:.2f})")

    nz = {n: sum(1 for r in rows if r[n]) for n in NAMES}
    print("\n  non-zero counts:")
    for n in NAMES:
        print(f"    {n:20} {nz[n]:>6,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
