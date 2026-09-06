"""Model comparison for the shortage-risk score — several algorithms, one harness.

    python3 ml/models.py              # compare every model at the default cutoff
    python3 ml/models.py --cutoff 2022-01-01

`ml/backtest.py` answers *"does concentration predict shortage"* (no, at either
layer — see `ml/upstream.py`). This file answers the next question: **given every
public signal we can compute before the cutoff, how good a predictor can we
actually build, and which algorithm wins?**

--------------------------------------------------------------------------------
Why the label is open-ended, and why that is forced rather than chosen
--------------------------------------------------------------------------------

The natural design is "did it go short within 12 months of the cutoff." That is
not available. openFDA purges resolved shortages — only 7 of 1,634 records are
`Resolved` — and the purge does not fall evenly across time. Onset years in
today's snapshot:

    2022: 172    2023: 355    2024: 11    2025: 179    2026: 299

**2024 has eleven.** That is not a quiet year for drug shortages; it is an
artefact of what survived to be downloaded. Label density varies ~30x between
adjacent years for reasons that have nothing to do with shortages, so a fixed
horizon inherits that noise directly: at 12 months the catalog yields 17
positives, at 36 months 82, open-ended 161.

So the label is **"appears in today's shortage snapshot with onset after the
cutoff."** That is a *prevalence* measure contaminated by survivorship, not a
clean incidence measure, and every number here should be read that way.

--------------------------------------------------------------------------------
Metrics — why AUC alone would mislead here
--------------------------------------------------------------------------------

The base rate is ~4%. On imbalanced data AUC flatters a model that ranks the
easy negatives well, so we also report:

  * **PR-AUC (average precision)** — the metric that actually degrades when a
    model cannot find the rare positives. Baseline is the base rate itself.
  * **precision@50** — of the 50 drugs we would actually put in front of a
    procurement officer, how many really went short. This is the number a buyer
    cares about, and it is the one to say on stage.

All figures are 5-fold cross-validated: every prediction is made by a model that
did not see that row.
"""

from __future__ import annotations

import json
import math
import random
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.backtest import (CACHE, MIN_PRODUCTS, SHORTAGE_URL, auc, fetch, key,  # noqa: E402
                         market_at, price_trend)
from ml.upstream import locate_countries  # noqa: E402

FOLDS = 5
TOP_K = 50


# --------------------------------------------------------------------------
# Features — everything knowable strictly before the cutoff
# --------------------------------------------------------------------------


def build(cutoff: date) -> tuple[list[str], dict[str, dict[str, float]], dict[str, int]]:
    labelers, forms = market_at(cutoff)
    trend = price_trend(cutoff.year - 1)
    upstream, _ = locate_countries(cutoff)

    recs = []
    for skip in (0, 1000):
        p = fetch(SHORTAGE_URL.format(skip=skip), CACHE / "openfda" / f"shortages_{skip}.json", 90)
        recs += json.loads(p.read_text()).get("results", [])
    prior, future = set(), set()
    for r in recs:
        try:
            onset = datetime.strptime(r.get("initial_posting_date") or "", "%m/%d/%Y").date()
        except ValueError:
            continue
        k = key(r.get("generic_name") or "")
        if not k:
            continue
        (prior if onset < cutoff else future).add(k)

    items = sorted(g for g in labelers if sum(labelers[g].values()) >= MIN_PRODUCTS)
    label = {g: (1 if g in future else 0) for g in items}

    def n_prod(g): return sum(labelers[g].values())
    def hhi(g):
        t = n_prod(g)
        return sum((c / t) ** 2 for c in labelers[g].values())
    def up_cnin(g):
        cs = upstream.get(g)
        return (sum(1 for c in cs if c in ("CHN", "IND")) / len(cs)) if cs else 0.0
    def up_countries(g):
        return float(len(set(upstream.get(g, ()))))

    feats = {
        "log product count": {g: math.log(n_prod(g)) for g in items},
        "sterile injectable": {g: (1.0 if any("INJECT" in f for f in forms[g]) else 0.0) for g in items},
        "downstream HHI": {g: hhi(g) for g in items},
        "price erosion (prior yr)": {g: -trend.get(g, 0.0) for g in items},
        "has price data": {g: (1.0 if g in trend else 0.0) for g in items},
        "prior shortage": {g: (1.0 if g in prior else 0.0) for g in items},
        "upstream CN+IN share": {g: up_cnin(g) for g in items},
        "upstream country count": {g: up_countries(g) for g in items},
        "distinct dosage forms": {g: float(len(forms[g])) for g in items},
    }
    return items, feats, label


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def average_precision(items, score, label) -> float:
    """PR-AUC. Degrades honestly when a model misses rare positives."""
    ranked = sorted(items, key=lambda g: -score[g])
    tp = 0
    total_pos = sum(label[g] for g in items)
    if not total_pos:
        return 0.0
    acc = 0.0
    for i, g in enumerate(ranked, 1):
        if label[g]:
            tp += 1
            acc += tp / i
    return acc / total_pos


def precision_at(items, score, label, k=TOP_K) -> float:
    ranked = sorted(items, key=lambda g: -score[g])[:k]
    return sum(label[g] for g in ranked) / len(ranked) if ranked else 0.0


# --------------------------------------------------------------------------
# Models — all stdlib, so nothing depends on a pip install at 4am
# --------------------------------------------------------------------------


def _standardise(rows):
    m = len(rows[0])
    mu = [sum(r[i] for r in rows) / len(rows) for i in range(m)]
    sd = [((sum((r[i] - mu[i]) ** 2 for r in rows) / len(rows)) ** 0.5) or 1.0 for i in range(m)]
    return [[(r[i] - mu[i]) / sd[i] for i in range(m)] for r in rows]


def fit_logistic(X, Y, l2=1.0, iters=2500, lr=0.5):
    w = [0.0] * (len(X[0]) + 1)
    for _ in range(iters):
        g = [0.0] * len(w)
        for x, y in zip(X, Y):
            z = w[0] + sum(a * b for a, b in zip(w[1:], x))
            p = 1 / (1 + math.exp(-max(-30, min(30, z))))
            d = p - y
            g[0] += d
            for j, xv in enumerate(x, 1):
                g[j] += d * xv
        n = len(X)
        w[0] -= lr * g[0] / n
        for j in range(1, len(w)):
            w[j] -= lr * (g[j] / n + l2 * w[j] / n)
    return lambda x: w[0] + sum(a * b for a, b in zip(w[1:], x)), w


def fit_stumps(X, Y, rounds=60, lr=0.3):
    """Gradient-boosted decision stumps. Captures non-linearity and interactions
    that logistic regression cannot, without a dependency."""
    m = len(X[0])
    base = math.log((sum(Y) + 1) / (len(Y) - sum(Y) + 1))
    trees = []
    F = [base] * len(X)
    for _ in range(rounds):
        resid = [y - 1 / (1 + math.exp(-max(-30, min(30, f)))) for y, f in zip(Y, F)]
        best = None
        for j in range(m):
            vals = sorted({x[j] for x in X})
            if len(vals) < 2:
                continue
            for q in (0.25, 0.5, 0.75):
                thr = vals[int(len(vals) * q)]
                lo = [r for x, r in zip(X, resid) if x[j] <= thr]
                hi = [r for x, r in zip(X, resid) if x[j] > thr]
                if len(lo) < 20 or len(hi) < 20:
                    continue
                gain = len(lo) * (sum(lo) / len(lo)) ** 2 + len(hi) * (sum(hi) / len(hi)) ** 2
                if best is None or gain > best[0]:
                    best = (gain, j, thr, sum(lo) / len(lo), sum(hi) / len(hi))
        if best is None:
            break
        _, j, thr, vlo, vhi = best
        trees.append((j, thr, vlo, vhi))
        for i, x in enumerate(X):
            F[i] += lr * (vlo if x[j] <= thr else vhi)

    def predict(x):
        s = base
        for j, thr, vlo, vhi in trees:
            s += lr * (vlo if x[j] <= thr else vhi)
        return s
    return predict


def cross_val(items, feats, label, fitter, seed=11):
    names = list(feats)
    raw = [[feats[n][g] for n in names] for g in items]
    X = _standardise(raw)
    Y = [float(label[g]) for g in items]
    rng = random.Random(seed)
    idx = list(range(len(items)))
    rng.shuffle(idx)
    oof = {}
    for f in range(FOLDS):
        test = set(idx[f::FOLDS])
        tr = [i for i in idx if i not in test]
        model = fitter([X[i] for i in tr], [Y[i] for i in tr])
        if isinstance(model, tuple):
            model = model[0]
        for i in test:
            oof[items[i]] = model(X[i])
    return oof


def main() -> int:
    cutoff = date(2023, 1, 1)
    if "--cutoff" in sys.argv:
        cutoff = date.fromisoformat(sys.argv[sys.argv.index("--cutoff") + 1])
    items, feats, label = build(cutoff)
    pos = sum(label.values())
    base = pos / len(items)
    print(f"MODEL COMPARISON — cutoff {cutoff}\n")
    print(f"  catalog {len(items):,} | positives {pos} | base rate {base:.1%}")
    print(f"  all figures are {FOLDS}-fold cross-validated (out-of-fold predictions only)\n")

    print(f"  {'single feature':<28}{'AUC':>7}{'PR-AUC':>9}{'P@50':>7}")
    for n, f in sorted(feats.items(), key=lambda kv: -abs((auc(items, kv[1], label) or 0.5) - 0.5)):
        a = auc(items, f, label)
        print(f"  {n:<28}{a:>7.3f}{average_precision(items, f, label):>9.3f}"
              f"{precision_at(items, f, label):>7.1%}")

    # SIZE-ONLY baseline. Most of the raw signal in this problem is "big drug
    # generates more shortage reports" - the reporting artefact documented in
    # backtest.py. Any honest claim has to be measured against that, not against
    # random, or we are taking credit for the confound.
    size_only = {k: feats[k] for k in ("log product count",)}

    print(f"\n  {'model':<28}{'AUC':>7}{'PR-AUC':>9}{'P@50':>7}   lift@50")
    results = {}
    for name, fitter, fs in (
            ("SIZE ONLY (the confound)", lambda X, Y: fit_logistic(X, Y, l2=1.0), size_only),
            ("logistic (L2=1.0)", lambda X, Y: fit_logistic(X, Y, l2=1.0), feats),
            ("logistic (L2=10, stronger)", lambda X, Y: fit_logistic(X, Y, l2=10.0), feats),
            ("boosted stumps", fit_stumps, feats)):
        oof = cross_val(items, fs, label, fitter)
        a = auc(items, oof, label)
        ap = average_precision(items, oof, label)
        pk = precision_at(items, oof, label)
        results[name] = (a, ap, pk)
        print(f"  {name:<28}{a:>7.3f}{ap:>9.3f}{pk:>7.1%}   {pk / base:>5.1f}x")

    print(f"\n  random baseline{'':<13}{0.5:>7.3f}{base:>9.3f}{base:>7.1%}    1.0x")
    size = results["SIZE ONLY (the confound)"]
    results = {k: v for k, v in results.items() if not k.startswith("SIZE ONLY")}
    best = max(results, key=lambda k: results[k][1])
    a, ap, pk = results[best]
    print(f"\n  ✅ best by PR-AUC: {best} — AUC {a:.3f}, PR-AUC {ap:.3f}, P@50 {pk:.0%}")
    print(f"  vs SIZE ONLY:            AUC {size[0]:.3f}, PR-AUC {size[1]:.3f}, P@50 {size[2]:.0%}")
    print(f"  -> the other eight features are worth "
          f"{ap - size[1]:+.3f} PR-AUC and {pk - size[2]:+.0%} precision@50 "
          f"OVER the confound.\n     That delta is the real contribution; the rest is bigness.")
    print(f"""
  The number to say on stage is P@50, not AUC:

    "Of the 50 drugs our score ranked highest at the start of 2023, {pk:.0%} went
     on to a shortage — against a {base:.1%} base rate. That is {pk / base:.0f}x better than
     picking at random, and it is measured on folds the model never saw."

  AUC is reported because it is standard, but with a {base:.1%} base rate it flatters
  any model that ranks easy negatives well. PR-AUC and precision@k are the honest
  ones, and the baseline for PR-AUC is the base rate itself.""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
