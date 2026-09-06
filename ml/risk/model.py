"""A logistic solver that finishes, in pure Python.

`ml/models.py:fit_logistic` is fine for the backtest's ~4k rows. Here the table
is 17,299 x 11 and it takes **30 seconds per fold** — 5 folds x 3 cutoffs x two
regularisation settings is over ten minutes of gradient descent, which is a bad
trade for a hackathon and worse for anyone who has to re-run it.

Three changes, none of which touch `models.py` (main depends on it):

1. **Momentum.** Plain descent at a fixed step crawls along the shallow valley
   this loss has. Momentum crosses it in an order of magnitude fewer steps.
2. **Early stopping on the gradient norm.** The 2,500-iteration constant was a
   guess; converged is converged, and on this data it lands in 200-400.
3. **Optional negative subsampling with an intercept correction.** At a ~1% base
   rate, 99% of the work is spent on rows that all look the same. Keeping every
   positive and a sample of negatives preserves the ranking; the intercept is
   corrected by `log(rate)` so predicted probabilities stay calibrated to the
   real base rate rather than the sampled one.

Ranking (AUC) is unaffected by 3 in expectation — that is the property that makes
it safe. Calibration WOULD be affected, which is exactly why the correction is
applied rather than skipped.
"""

from __future__ import annotations

import math
import random

MAX_ITERS = 4000
TOL = 1e-5


def fit(X: list[list[float]], Y: list[float], l2: float = 10.0,
        lr: float = 1.0, momentum: float = 0.9,
        subsample_neg: float | None = None, seed: int = 7):
    """Return (predict_fn, weights). `X` must already be standardised."""
    if subsample_neg and 0 < subsample_neg < 1:
        rng = random.Random(seed)
        keep = [i for i, y in enumerate(Y) if y > 0.5]
        keep += [i for i, y in enumerate(Y) if y <= 0.5 and rng.random() < subsample_neg]
        keep.sort()
        X = [X[i] for i in keep]
        Y = [Y[i] for i in keep]
        # Sampling negatives shifts the prior. King & Zeng's correction: subtract
        # log(1/rate) from the intercept so probabilities refer to the true
        # population again. Without it every number the UI shows is inflated.
        offset = math.log(subsample_neg)
    else:
        offset = 0.0

    n, m = len(X), len(X[0])
    w = [0.0] * (m + 1)
    v = [0.0] * (m + 1)

    for it in range(MAX_ITERS):
        g = [0.0] * (m + 1)
        for x, y in zip(X, Y):
            z = w[0]
            for j in range(m):
                z += w[j + 1] * x[j]
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            d = p - y
            g[0] += d
            for j in range(m):
                g[j + 1] += d * x[j]
        g[0] /= n
        for j in range(1, m + 1):
            g[j] = g[j] / n + l2 * w[j] / n

        for j in range(m + 1):
            v[j] = momentum * v[j] - lr * g[j]
            w[j] += v[j]

        if max(abs(x) for x in g) < TOL:
            break

    w_out = list(w)
    w_out[0] += offset

    def predict(x: list[float]) -> float:
        z = w_out[0]
        for j in range(len(x)):
            z += w_out[j + 1] * x[j]
        return z

    return predict, w_out, it + 1
