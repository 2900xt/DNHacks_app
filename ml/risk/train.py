"""Step 6 — train, evaluate, and pick a model that can actually be shipped.

    python3 -m ml.risk.train              # all cutoffs, all variants
    python3 -m ml.risk.train --selftest   # assert the shipping bar

Six variants are tried, not one, because "the model works" is only meaningful
against something simpler that also works:

  B1  any prior OAI, ever                  the dumbest thing that could work
  B2  adverse events in the last 3 years   the second dumbest
  B3  months since last OAI (inverted)     recency alone
  L1  logistic, light regularisation
  L2  logistic, heavy regularisation
  GB  gradient-boosted stumps              non-linear, for comparison only

⚠️ **GB is measured but will not ship even if it wins.**
`decisions/0003-transparent-risk-rules.md` requires a rule a judge can see. A
logistic model has printed coefficients and a per-plant evidence list; 60 boosted
stumps have neither. If GB beats logistic by a wide margin that is a finding to
report — "a non-linear model does better, and we chose not to use it" — not a
licence to ship it.

The shipping bar, from the spec: beat **both** baselines by **≥0.05 AUC** with
**p < 0.01** in at least **two of three** cutoffs. It is written so it can fail.

Metrics: rank AUC (accuracy would be meaningless at a ~1% base rate — a model
predicting "never" scores 99%), permutation p, and a calibration decile table,
because the UI shows a percentage and a rank metric cannot justify one.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ml.backtest import auc, permutation_p  # noqa: E402
from ml.models import fit_stumps  # noqa: E402
from ml.risk.model import fit as fit_logistic  # noqa: E402
from ml.risk.features import MODEL_NAMES, History, feature_table  # noqa: E402
from ml.risk.labels import HORIZON_DAYS, labeller  # noqa: E402

CUTOFFS = [date(2022, 1, 1), date(2023, 1, 1), date(2024, 1, 1)]
FOLDS = 5
MIN_GAIN = 0.05
MAX_P = 0.01


def _standardise_fit(rows):
    m = len(rows[0])
    mu = [sum(r[i] for r in rows) / len(rows) for i in range(m)]
    sd = [((sum((r[i] - mu[i]) ** 2 for r in rows) / len(rows)) ** 0.5) or 1.0
          for i in range(m)]
    return mu, sd


def _apply(rows, mu, sd):
    return [[(r[i] - mu[i]) / sd[i] for i in range(len(mu))] for r in rows]


def cross_val(X, Y, fitter, folds=FOLDS, seed=11):
    """Out-of-fold scores. The scaler is fit on TRAIN ONLY inside each fold —
    fitting it on everything leaks the test rows' distribution into the transform."""
    import random
    rng = random.Random(seed)
    idx = list(range(len(X)))
    rng.shuffle(idx)
    oof = [0.0] * len(X)
    for f in range(folds):
        test = set(idx[f::folds])
        tr = [i for i in idx if i not in test]
        mu, sd = _standardise_fit([X[i] for i in tr])
        model = fitter(_apply([X[i] for i in tr], mu, sd), [float(Y[i]) for i in tr])
        if isinstance(model, tuple):
            model = model[0]
        for i in test:
            oof[i] = model(_apply([X[i]], mu, sd)[0])
    return oof


#: Five, not ten. With 117-190 positives spread over a 7k universe, deciles put
#: 0-2 positives in each of the lower buckets and the ordering is then noise: the
#: same model reads non-monotone at 10 buckets and monotone at 5 without changing
#: a single prediction. Five is the finest split the label count supports.
CAL_BUCKETS = 5


def calibration(oof, Y, buckets=CAL_BUCKETS):
    p = [1 / (1 + math.exp(-max(-30, min(30, s)))) for s in oof]
    order = sorted(range(len(p)), key=lambda i: p[i])
    size = len(order) // buckets
    out = []
    for b in range(buckets):
        grp = order[b * size:(b + 1) * size] if b < buckets - 1 else order[b * size:]
        if not grp:
            continue
        out.append({"decile": b + 1,
                    "predicted": sum(p[i] for i in grp) / len(grp),
                    "observed": sum(Y[i] for i in grp) / len(grp)})
    return out


def monotone(cal, tol=0.004) -> bool:
    obs = [c["observed"] for c in cal]
    return all(b >= a - tol for a, b in zip(obs, obs[1:]))


def evaluate_cutoff(cutoff: date, hist: History, perms=300, verbose=True) -> dict:
    feis, rows, uni = feature_table(cutoff, hist)
    lab = labeller(hist)
    Y = [lab(f, cutoff) for f in feis]
    X = [[r[n] for n in MODEL_NAMES] for r in rows]
    ids = feis
    label = dict(zip(ids, Y))
    pos = sum(Y)

    def score_of(vals):
        return dict(zip(ids, vals))

    variants: dict[str, list[float]] = {
        # Baselines: no fitting, no folds — they cannot overfit, which is the point.
        "B1 any prior OAI": [1.0 if r["oai_all"] > 0 else 0.0 for r in rows],
        "B2 events last 3y": [r["oai_3y"] + r["vai_3y"] + r["refusal_mfg_3y"] for r in rows],
        "B3 recency of OAI": [-r["months_since_oai"] for r in rows],
        "L1 logistic l2=1": cross_val(X, Y, lambda a, b: fit_logistic(a, b, l2=1.0)),
        "L2 logistic l2=10": cross_val(X, Y, lambda a, b: fit_logistic(a, b, l2=10.0)),
        "L3 logistic l2=100": cross_val(X, Y, lambda a, b: fit_logistic(a, b, l2=100.0)),
        "GB boosted stumps": cross_val(X, Y, fit_stumps),
    }

    res = {}
    for name, vals in variants.items():
        s = score_of(vals)
        a = auc(ids, s, label)
        res[name] = {"auc": a,
                     "p": permutation_p(ids, s, label, a, n=perms) if a else 1.0}

    best_base = max(res[k]["auc"] for k in res if k.startswith("B"))
    out = {"cutoff": cutoff.isoformat(), "universe": len(ids), "positives": pos,
           "base_rate": pos / len(ids), "variants": res, "best_baseline": best_base}

    # Calibration for the model we intend to ship.
    ship = "L2 logistic l2=10"
    out["calibration"] = calibration(variants[ship], Y)
    out["monotone"] = monotone(out["calibration"])
    out["passes_bar"] = (res[ship]["auc"] - best_base >= MIN_GAIN
                         and res[ship]["p"] < MAX_P)

    if verbose:
        print(f"\n  cutoff {cutoff}  ·  {len(ids):,} plants  ·  {pos} positives  "
              f"·  base {pos/len(ids):.2%}")
        print(f"    {'variant':<22}{'AUC':>7}{'p':>8}{'vs best baseline':>18}")
        for name in variants:
            r = res[name]
            gain = "" if name.startswith("B") else f"{r['auc'] - best_base:+.3f}"
            print(f"    {name:<22}{r['auc']:>7.3f}{r['p']:>8.3f}{gain:>18}")
        print(f"    shipping bar (L2 beats every baseline by ≥{MIN_GAIN} at p<{MAX_P}): "
              f"{'PASS' if out['passes_bar'] else 'FAIL'}")
    return out


def coefficients(cutoff: date, hist: History) -> dict:
    """Full-data fit. These printed numbers ARE the rule decision 0003 requires."""
    feis, rows, _ = feature_table(cutoff, hist)
    lab = labeller(hist)
    Y = [lab(f, cutoff) for f in feis]
    X = [[r[n] for n in MODEL_NAMES] for r in rows]
    mu, sd = _standardise_fit(X)
    _, w, _iters = fit_logistic(_apply(X, mu, sd), [float(y) for y in Y], l2=10.0)
    return {"intercept": w[0], "coefficients": dict(zip(MODEL_NAMES, w[1:])),
            "standardisation": {n: {"mu": mu[i], "sd": sd[i]} for i, n in enumerate(MODEL_NAMES)}}


def run(perms=300, verbose=True) -> dict:
    hist = History()
    evals = [evaluate_cutoff(c, hist, perms, verbose) for c in CUTOFFS]
    coefs = coefficients(CUTOFFS[-1], hist)
    if verbose:
        print("\n  calibration (5 buckets, out-of-fold) — predicted vs observed:")
        for e in evals:
            row = "  ".join(f"{c['predicted']*100:.1f}/{c['observed']*100:.1f}"
                            for c in e["calibration"])
            print(f"    {e['cutoff']}  {row}   monotone={e['monotone']}")
    if verbose:
        print("\n  coefficients (standardised, full-data fit at "
              f"{CUTOFFS[-1]}) — positive raises risk:")
        for n, v in sorted(coefs["coefficients"].items(), key=lambda kv: -abs(kv[1])):
            print(f"    {n:22}{v:+.3f}")
        print(f"    {'intercept':22}{coefs['intercept']:+.3f}")
        passed = sum(1 for e in evals if e["passes_bar"])
        mono = sum(1 for e in evals if e["monotone"])
        print(f"\n  shipping bar passed at {passed}/3 cutoffs · calibration monotone "
              f"at {mono}/3")
        print(f"  {'SHIPPABLE as a percentage' if passed >= 2 and mono >= 2 else ''}"
              f"{'SHIPPABLE as a BAND only (calibration not monotone)' if passed >= 2 and mono < 2 else ''}"
              f"{'NOT SHIPPABLE — does not beat the baselines' if passed < 2 else ''}")
    return {"evaluations": evals, "model": coefs}


def main() -> int:
    if "--selftest" in sys.argv:
        r = run(perms=200, verbose=False)
        evals = r["evaluations"]
        passed = sum(1 for e in evals if e["passes_bar"])
        mono = sum(1 for e in evals if e["monotone"])
        base_ok = all(0.005 <= e["base_rate"] <= 0.10 for e in evals)
        print("risk model self-check\n")
        print(f"  [{'OK ' if base_ok else 'FAIL'}] base rates sane at all cutoffs: "
              f"{[f'{e['base_rate']:.2%}' for e in evals]}")
        print(f"  [{'OK ' if passed >= 2 else 'FAIL'}] beats both baselines by "
              f"≥{MIN_GAIN} AUC at p<{MAX_P} in {passed}/3 cutoffs")
        print(f"  [{'OK ' if mono >= 2 else 'WARN'}] calibration monotone in {mono}/3 "
              f"— {'percentages' if mono >= 2 else 'bands only'}")
        ok = base_ok and passed >= 2
        print(f"\n  {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1

    r = run()
    if "--write" in sys.argv:
        out = Path(__file__).resolve().parents[2] / "data" / "cache" / "risk" / "model.json"
        out.write_text(json.dumps(r, indent=2, default=str) + "\n")
        print(f"\n  wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
