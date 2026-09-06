"""Step 5 — the label: did this plant have FDA-recorded trouble in the next 12 months?

    python3 -m ml.risk.labels [--cutoff 2023-01-01]

Positive if, in `(cutoff, cutoff + 365d]`, the FEI has **any** of:

  * an inspection classified **OAI** (by inspection END date)
  * a **manufacturing** import refusal — charge 27 or 3280

Deliberately NOT a positive:

  * **paperwork refusals** (118 / 472). "Not listed with FDA" and "labeling not
    in English" are administrative stops. Counting them as disruptions would
    inflate the base rate with events that never interrupted a shipment of
    anything anyone was relying on. They stay a weak *feature*, never a label.
  * **VAI**. It is the step before OAI, not a failure.

⚠️ **OAI lag, stated rather than hidden.** The classification posts months after
the inspection ends. We label by END date, which is when the trouble happened —
but a real user would not have learned of it until later. So the model is
predicting *when a plant went wrong*, not *when the world found out*. Any claim
about lead time has to say that.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ml.risk.features import History  # noqa: E402
from ml.risk.universe import universe  # noqa: E402

HORIZON_DAYS = 365


def labeller(hist: History):
    def label(fei: str, cutoff: date) -> int:
        end = cutoff + timedelta(days=HORIZON_DAYS)
        for d, c in hist.insp.get(fei, ()):
            if cutoff < d <= end and c == "OAI":
                return 1
        for d, k in hist.refu.get(fei, ()):
            if cutoff < d <= end and k == "mfg":
                return 1
        return 0
    return label


def main() -> int:
    cut = date(2023, 1, 1)
    if "--cutoff" in sys.argv:
        cut = date.fromisoformat(sys.argv[sys.argv.index("--cutoff") + 1])
    hist = History()
    lab = labeller(hist)
    uni = universe(cut)
    ys = [lab(f, cut) for f in sorted(uni)]
    base = sum(ys) / len(ys)
    print(f"LABELS at {cut} (+{HORIZON_DAYS}d)\n")
    print(f"  universe {len(ys):,} · positives {sum(ys):,} · base rate {base:.2%}")
    ok = 0.005 <= base <= 0.10
    print(f"  [{'OK ' if ok else 'CHECK'}] base rate in 0.5–10% "
          + ("" if ok else "— above 10% usually means the universe collapsed back "
                           "to the signals file, which is all-positive by construction"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
