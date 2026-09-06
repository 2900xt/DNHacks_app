"""Isotonic recalibration — make the percentage mean what it says.

The raw logistic model ranks well and is wildly over-confident at the top. Out
of fold, on the training population:

    median 1.15%   ·   p90 4.73%   ·   p99 20.25%   ·   max 99.99%

    plants scored >20%: 75, of which 27 actually had an event — **36%**

So a plant the model calls 99% belongs to a group that fails 36% of the time.
The ordering is right (36% against a 1.7% base rate is a 21x lift and exactly
what a shortlist needs); the number is not, and a number that is not true is
worse than a band.

Clipping the inputs was the wrong instinct — the extreme feature values are real
plants with real refusal histories, not corrupt rows. The over-confidence comes
from a linear logit having no ceiling, not from bad data.

**Pool-adjacent-violators** fixes the number without touching the order: sort the
out-of-fold predictions, take observed frequencies, and merge any adjacent pair
that goes the wrong way until the sequence is monotone. It is the standard
answer, it cannot reorder anything, and it is about forty lines.

Fitted on out-of-fold predictions only — fitting it on in-sample scores would
calibrate the model to answers it had already seen.
"""

from __future__ import annotations

import math


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def fit_isotonic(scores: list[float], labels: list[int], min_bin: int = 40):
    """Return breakpoints mapping a raw logit to a calibrated probability.

    `min_bin` keeps each block big enough that its observed rate is not one
    positive's worth of noise: with ~170 positives in 7,300 rows, blocks smaller
    than a few dozen say nothing.
    """
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    blocks = [[scores[i], float(labels[i]), 1] for i in order]   # [score, sum, n]

    # Pre-pool into fixed-size bins so PAVA operates on stable rates. Each bin
    # carries the SUM of its scores, so its anchor can be the mean.
    pooled = []
    for i in range(0, len(blocks), min_bin):
        chunk = blocks[i:i + min_bin]
        pooled.append([sum(c[0] for c in chunk), sum(c[1] for c in chunk),
                       sum(c[2] for c in chunk)])

    # Fold a short trailing remainder into its neighbour. `len % min_bin` lands
    # in the HIGHEST-scoring block, which is the one every headline number comes
    # from — left alone, 7,330 rows at min_bin=40 ended with a block of 10 whose
    # 8 positives set the ceiling at 80% on the strength of ten plants.
    if len(pooled) > 1 and pooled[-1][2] < min_bin:
        tail = pooled.pop()
        for j in range(3):
            pooled[-1][j] += tail[j]

    # Pool adjacent violators: merge any bin whose rate is below its predecessor.
    changed = True
    while changed:
        changed = False
        out = []
        for b in pooled:
            if out and (out[-1][1] / out[-1][2]) > (b[1] / b[2]):
                for j in range(3):
                    out[-1][j] += b[j]
                changed = True
            else:
                out.append(list(b))
        pooled = out

    # `at` is the MEAN score of the block, not its maximum. Anchoring a block's
    # rate at its top edge is subtly and consistently wrong: interpolating from
    # the previous block up to that edge puts every member of the block BELOW its
    # own observed rate, which showed up as under-prediction in all six bands
    # (0.36% predicted against 0.58% observed, 12.5% against 16.8%, and so on).
    # With the mean as the anchor, half the block interpolates up and half down.
    return [{"at": b[0] / b[2], "p": b[1] / b[2], "n": b[2]} for b in pooled]


def _bracket(bins: list[dict], score: float):
    """The two blocks a score falls between, and how far along it sits.

    Shared by `apply_isotonic` and `interval` so the two cannot disagree. They
    did: `interval` used to snap to the NEAREST block while `apply_isotonic`
    interpolated between two, which left 46 plants whose p12 sat outside their
    own published range.
    """
    if score <= bins[0]["at"]:
        return bins[0], bins[0], 0.0
    for a, b in zip(bins, bins[1:]):
        if score <= b["at"]:
            span = b["at"] - a["at"]
            return a, b, (0.0 if span <= 0 else (score - a["at"]) / span)
    return bins[-1], bins[-1], 0.0


def apply_isotonic(bins: list[dict], score: float) -> float:
    """Map a raw logit onto the calibrated curve, interpolating between blocks."""
    if not bins:
        return _sigmoid(score)
    a, b, t = _bracket(bins, score)
    return a["p"] + t * (b["p"] - a["p"])


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for k successes in n. Finite at k=0 and k=n."""
    if n == 0:
        return 0.0, 1.0
    p, z2 = k / n, z * z
    d = 1 + z2 / n
    c = (p + z2 / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def _selftest() -> int:
    """Two claims, both checkable: isotonic does not reorder, and after it the
    percentage matches the observed frequency."""
    import sys
    from datetime import date
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ml.backtest import auc
    from ml.risk.features import MODEL_NAMES, History, feature_table
    from ml.risk.labels import labeller
    from ml.risk.model import fit
    from ml.risk.train import cross_val

    cutoff = date(2025, 8, 1)
    hist = History()
    feis, rows, _ = feature_table(cutoff, hist)
    lab = labeller(hist)
    Y = [lab(f, cutoff) for f in feis]
    X = [[r[n] for n in MODEL_NAMES] for r in rows]
    oof = cross_val(X, [float(y) for y in Y], lambda a, b: fit(a, b, l2=10.0))
    bins = fit_isotonic(oof, Y)
    cal = [apply_isotonic(bins, s) for s in oof]

    print(f"CALIBRATION  {len(oof):,} out-of-fold scores, {sum(Y)} positives, "
          f"base rate {sum(Y)/len(Y)*100:.2f}%")

    ids = list(range(len(Y)))
    lab_d = dict(zip(ids, Y))
    a_raw = auc(ids, dict(zip(ids, oof)), lab_d)
    a_cal = auc(ids, dict(zip(ids, cal)), lab_d)

    # The right invariant is NO INVERSION, not equal AUC. Isotonic maps blocks to
    # a single rate, so plants inside a block become tied — and AUC scores a tie
    # as half a win, which costs a few ten-thousandths without any pair ever
    # being put in the wrong order. Asserting equal AUC would fail a correct
    # implementation; assert what actually matters instead.
    o = sorted(range(len(oof)), key=lambda i: oof[i])
    inversions = sum(1 for a, b in zip(o, o[1:]) if cal[b] < cal[a] - 1e-12)
    ok_rank = inversions == 0
    print(f"  [{'OK ' if ok_rank else 'FAIL'}] no pair inverted ({inversions} "
          f"inversions) — AUC {a_raw:.4f} raw vs {a_cal:.4f} calibrated, the "
          f"{a_raw - a_cal:.4f} gap being ties inside blocks, not reordering")

    ok_mono = all(b["p"] >= a["p"] for a, b in zip(bins, bins[1:]))
    print(f"  [{'OK ' if ok_mono else 'FAIL'}] curve monotone — {len(bins)} blocks, "
          f"{bins[0]['p']*100:.2f}% → {bins[-1]['p']*100:.1f}%")

    # The claim the whole thing exists to make: what we print is what happens.
    print(f"\n  {'predicted':>10}{'observed':>10}{'n':>7}  {'95% Wilson':^15} verdict")
    worst, sig = 0.0, 0
    for r in reliability(bins, oof, Y):
        sig += not r["inside"]
        worst = max(worst, abs(r["predicted"] - r["observed"]))
        print(f"  {r['predicted']*100:>9.2f}%{r['observed']*100:>9.2f}%{r['n']:>7,}  "
              f"[{r['range'][0]*100:>5.1f}–{r['range'][1]*100:>5.1f}%]  "
              f"{'inside' if r['inside'] else 'OUTSIDE'}")

    ok_fit = sig == 0
    print(f"\n  [{'OK ' if ok_fit else 'FAIL'}] every band's prediction inside the "
          f"95% interval of what was observed")

    # And the thing this replaced: the raw sigmoid's top-end claim.
    raw_p = [1 / (1 + math.exp(-max(-30, min(30, s)))) for s in oof]
    hi = [i for i, r in enumerate(raw_p) if r > 0.20]
    if hi:
        print(f"\n  before: {len(hi)} plants raw-scored >20% (max "
              f"{max(raw_p)*100:.1f}%), of which {sum(Y[i] for i in hi)} had an "
              f"event — {sum(Y[i] for i in hi)/len(hi)*100:.0f}% actual")
        print(f"  after:  the same {len(hi)} plants now read "
              f"{min(cal[i] for i in hi)*100:.1f}–{max(cal[i] for i in hi)*100:.1f}%")
    return 0 if (ok_rank and ok_mono and ok_fit) else 1




def interval(bins: list[dict], score: float) -> tuple[float, float]:
    """95% interval for a score, from the block it lands in.

    A single percentage hides how much is behind it: the top block is 46% on 50
    plants, which is 32-60%, while a mid block is 6.5% on 320 and much tighter.
    The UI can then say "46% (32-60%)" instead of implying three digits of
    precision that fifty plants cannot support.
    """
    if not bins:
        return 0.0, 1.0
    a, b, t = _bracket(bins, score)
    la, ha = wilson(round(a["p"] * a["n"]), a["n"])
    lb, hb = wilson(round(b["p"] * b["n"]), b["n"])
    # Interpolate the BOUNDS on the same bracket and the same t as the estimate.
    # Because each block's own p sits inside its own interval, convexity then
    # guarantees the interpolated p12 sits inside the interpolated range.
    return la + t * (lb - la), ha + t * (hb - ha)


#: The bands the reliability table is reported over. Not deciles: at a 2.35% base
#: rate the top decile holds nearly every positive and the lower nine are noise,
#: so the split is by what the number would MEAN to someone reading it.
REPORT_BANDS = [(0.0, 0.01), (0.01, 0.02), (0.02, 0.05),
                (0.05, 0.10), (0.10, 0.25), (0.25, 1.01)]


def reliability(bins: list[dict], scores: list[float], labels: list[int]) -> list[dict]:
    """Predicted vs observed, out of fold. The whole claim, in one table.

    This is the evidence that the percentage is a percentage. A model can rank
    perfectly and still be wrong about magnitude — this one was, reaching 100%
    for a group that failed 36% of the time — and no rank metric can detect it.
    """
    cal = [apply_isotonic(bins, s) for s in scores]
    out = []
    for lo, hi in REPORT_BANDS:
        grp = [i for i, c in enumerate(cal) if lo <= c < hi]
        if not grp:
            continue
        k = sum(labels[i] for i in grp)
        w_lo, w_hi = wilson(k, len(grp))
        out.append({
            "predicted": round(sum(cal[i] for i in grp) / len(grp), 5),
            "observed": round(k / len(grp), 5),
            "n": len(grp),
            "range": [round(w_lo, 5), round(w_hi, 5)],
            "inside": bool(w_lo <= sum(cal[i] for i in grp) / len(grp) <= w_hi),
        })
    return out


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
