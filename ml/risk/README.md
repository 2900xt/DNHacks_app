# Next-failure model — plant-level disruption risk

> Spec: `../../../DNHacks_brain/project/PREDICT_NEXT_FAILURE.md`.
> Built Sun 06 Sep on branch `predict-failure`. **Not merged. UI untouched.**

Answers *"which of my suppliers is most likely to break next, and how likely?"* —
one calibrated percentage per plant, with the evidence that produced it.

```
make risk         rebuild web/data/risk.json          (~1 min)
make risk-train   compare six models, three cutoffs   (~40 s)
make risk-check   assert the shipping bar             (~30 s)
```

## The result

| cutoff | plants | positives | base | **model AUC** | best baseline | gain |
|---|---:|---:|---:|---:|---:|---:|
| 2022-01-01 | 7,272 | 117 | 1.61% | **0.782** | 0.703 | +0.079 |
| 2023-01-01 | 7,174 | 117 | 1.63% | **0.814** | 0.706 | +0.108 |
| 2024-01-01 | 6,809 | 117 | 1.72% | **0.782** | 0.703 | +0.079 |

Shipping bar (beat **both** baselines by ≥0.05 AUC at p<0.01): **3/3**.
Calibration monotone at **2/3**, and the top bucket lands 5.0–5.6% predicted
against 5.4–6.1% observed — so the number on screen is a percentage, not a vibe.

The sentence a presenter can say:

> *"On plants the FDA actively inspects, this predicts the next failed inspection
> or refused shipment a year out with AUC 0.78–0.81, against 0.70 for simply
> asking whether the plant has ever failed before."*

## Six models tried, and the transparent one won

| | AUC (2023) | |
|---|---:|---|
| B1 any prior OAI | 0.671 | the dumbest thing that could work |
| B2 events last 3y | 0.706 | best baseline |
| B3 recency of OAI | 0.672 | |
| L1 logistic l2=1 | 0.811 | |
| **L2 logistic l2=10** | **0.814** | **ships** |
| L3 logistic l2=100 | 0.808 | over-regularised |
| GB boosted stumps | 0.641 | **worse than the baselines** |

Gradient boosting was measured because it should be, and it **lost** — badly, at
every cutoff. So there is no tension with
`decisions/0003-transparent-risk-rules.md`: the model with printed coefficients
is also the most accurate one. That is worth saying out loud, because the usual
version of this trade-off is "we gave up accuracy for explainability".

## The two decisions that made it work

**1. The universe excludes plants FDA is not looking at.**

The label is "FDA recorded trouble", so a plant nobody inspects cannot produce
one. Measured at 2024: plants inspected within 3 years have a **2.01%** positive
rate; plants unseen for a decade, **0.21%**. A model over everyone learns FDA's
*schedule*, not plant risk. Restricting to inspected-within-5-years halves the
universe and **raises** AUC (0.805 → 0.814), because the rows it drops were easy
negatives that flattered the score.

**2. The two inspection-cadence features are computed but withheld from the fit.**

`insp_3y` and `months_since_insp` are needed for the evidence lines ("last
inspected 30 months ago") and are poison in the model: `months_since_insp` fits
at −0.540 (longer since inspection = safer — true, useless), and `insp_3y` flips
sign between the univariate view (0.615) and the multivariate fit (−0.408).
Neither is explainable in one sentence, which is the spec's own bar. Dropping
them costs 0.003 AUC.

## Evidence is ordered by what moved the score

Not by template. Sandoz reads *"1 shipment refused at the border on paperwork"*
first because that contributes **+1.53** to its logit — written in template order
its first line was *"no failed FDA inspection on record"*, which is true and the
opposite of what the model believes.

```
Zhuhai United Laboratories     10.0%  high     4 failed FDA inspections on record…
Sharp Sterile Manufacturing     8.4%  high     2 failed FDA inspections on record…
Centrient Pharmaceuticals IN    8.1%  high     3 failed FDA inspections on record…
Sandoz GmbH                     6.6%  high     1 shipment refused on paperwork…
```

## News enrichment annotates; it never moves the number

`python3 -m ml.risk.news` searches for what FDA records structurally cannot
contain — fires, export bans, closures, a firm exiting the market. On the current
top 8 it ran **4 searches per plant and found nothing**, recorded as
`findings: [], parse_failed: false` so "clean" is distinguishable from "the call
broke".

`p12` is not adjusted. A `suggested_adjustment` is recorded and **never applied**:
the model is calibrated and reproducible, and an LLM nudging a calibrated number
destroys both properties silently. A human raising a number because a plant caught
fire is a good decision; the system doing it invisibly is not.

## Files

| | |
|---|---|
| `inspections.py` | 39,675 Drugs inspections, all countries/classifications |
| `refusals.py` | 13,681 refusal events, 2014→2026, mfg vs paperwork split |
| `universe.py` | who is scoreable, and the active-inspection restriction |
| `features.py` | the nine model features + two evidence-only ones |
| `labels.py` | OAI or manufacturing refusal within 365 days |
| `model.py` | logistic with momentum + early stop — 30 s/fold → 3 s |
| `train.py` | six variants, three cutoffs, AUC + permutation p + calibration |
| `emit.py` | `web/data/risk.json` |
| `news.py` | optional web-search annotation |

## Honest limits

- **It predicts FDA-recorded trouble.** Export bans, fires, and a firm quietly
  leaving the US market are in no federal record. That is what `news.py` is for
  and why `not_modelled` ships inside the artifact.
- **OAI posts months after the inspection ends.** Labels use the END date — when
  the trouble happened, not when the world learned of it. Any lead-time claim has
  to say that.
- **Never report accuracy.** At a 1.7% base rate, "never fails" scores 98%.
- **117–190 positives per cutoff.** Calibration is credible at 5 buckets and
  noise at 10; the finest split the label count supports is what is used.
