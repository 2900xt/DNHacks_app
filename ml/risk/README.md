# Next-failure model — plant-level disruption risk

> Spec: `../../../DNHacks_brain/project/PREDICT_NEXT_FAILURE.md`.
> Built Sun 06 Sep on branch `predict-failure`. **Not merged. UI untouched.**

Answers *"which of my suppliers is most likely to break next, and how likely?"* —
one calibrated percentage per plant, with the evidence that produced it.

```
make risk         rebuild web/data/risk.json          (~1 min)
make risk-train   compare six models, three cutoffs   (~40 s)
make risk-check   assert the shipping bar + calibration (~60 s)
```

Covers **1,706 of the 1,732 nodes the UI can draw (98.5%)** — 925 scored directly
from FDA history, 781 inherited from the plant that makes them. The 26 that are
not covered are company names we could not resolve to one establishment, and they
are left blank on purpose.

## The result

| cutoff | plants | positives | base | **model AUC** | best baseline | gain |
|---|---:|---:|---:|---:|---:|---:|
| 2022-01-01 | 7,272 | 117 | 1.61% | **0.782** | 0.703 | +0.079 |
| 2023-01-01 | 7,174 | 117 | 1.63% | **0.814** | 0.706 | +0.108 |
| 2024-01-01 | 6,809 | 117 | 1.72% | **0.782** | 0.703 | +0.079 |

Shipping bar (beat **both** baselines by ≥0.05 AUC at p<0.01): **3/3**.
Percentages are isotonically recalibrated on out-of-fold scores and every band
lands inside the 95% interval of what was observed — so the number on screen is a
percentage, not a vibe. See the next section for what it took to be able to say
that.

The sentence a presenter can say:

> *"On plants the FDA actively inspects, this predicts the next failed inspection
> or refused shipment a year out with AUC 0.78–0.81, against 0.70 for simply
> asking whether the plant has ever failed before."*

## The number was over-confident, and that is now fixed

The first version shipped **99.9%** for the worst plants. It was wrong, and the
way it was wrong is worth showing, because it is the failure mode every risk demo
has and almost none of them check for.

Out of fold, on the training population:

```
  75 plants scored above 20%   —   max 100.0%
  of those, 27 actually had an event   —   36%
```

The **ranking** was excellent: 36% against a 2.35% base rate is a 15x lift, which
is exactly what a shortlist is for. The **number** was fiction. A logistic model
is linear in the logit and has no ceiling, so a plant with 44 refusals — 22
standard deviations past anything in training, because most plants have zero —
extrapolates straight to certainty.

The reflex fix is to clip the inputs. That would have been wrong: those refusal
counts are real, and clipping them throws away the signal that makes those plants
interesting. The problem was never the inputs, it was mapping a logit to a
probability the data never supported.

**Isotonic regression (pool-adjacent-violators) on 5-fold out-of-fold scores**
fixes the number without touching the order:

| | predicted | observed | n | 95% interval | |
|---|---:|---:|---:|:---:|---|
| | 0.46% | 0.57% | 3,688 | 0.4–0.9% | inside |
| | 1.60% | 2.20% | 1,456 | 1.6–3.1% | inside |
| | 2.54% | 1.90% | 1,264 | 1.3–2.8% | inside |
| | 6.79% | 5.96% | 604 | 4.3–8.1% | inside |
| | 13.51% | 13.23% | 257 | 9.6–17.9% | inside |
| | **35.38%** | **40.98%** | 61 | 29.5–53.5% | inside |

Every band's prediction lands inside the 95% Wilson interval of what actually
happened, **0 pairs are inverted**, and AUC is unchanged at 0.7919. The same 75
plants that used to read up to 100% now read 20.6–46.0%.

The curve is flat above its top block, which is the point: 46% is the highest
rate ever observed at any score, so no plant is shown above it. 18 of 950 plants
(1.9%) sit on that ceiling and carry `at_ceiling: true` — rank inside that group
with `p12_uncalibrated`. Every plant also ships `p12_range`, because "46%" from
50 plants is really 33–60% and a bare number implies precision that is not there.

Two bugs in the *test* had to be fixed before it could say this. Asserting equal
AUC failed a correct implementation — isotonic ties plants inside a block and AUC
scores a tie as half a win — so the assertion is now "no pair inverted". And the
normal-approximation error bar is exactly zero when observed hits 0% or 100%, so
six plants that all failed "rejected" every possible prediction; it uses Wilson
intervals now, which stay finite at the boundaries.

## Every node gets a number, not just the plants

925 nodes have FDA history of their own. The other 781 the UI can draw — products,
APIs, drugs, precursors — are not places and have no record, so they inherit the
risk of the worst plant behind them, propagated along the graph and named in
`inherited_from`. Worst-case rather than average, for the same reason each plant
takes its worst site: a second supplier does not cover the first one's shutdown
unless it can absorb the volume, and nothing in these files says whether it can.

That propagation caught a real error. `core_tokens` strips place names by design
— the WuXi lesson — but stripping them makes `UNITED LABORATORIES CHENGDU` and
`Zhuhai United Laboratories` the identical core `{united, laboratories}` and a
perfect 1.00 match. Unguarded, **6-APA — the headline chokepoint — inherited four
failed inspections belonging to a plant 1,500 km away**, and the curated node
said so in its own attrs the whole time: *"DECRS carries TUL Inner Mongolia and
Zhuhai, not the Chengdu site"*. A GEO token can now **veto** a match but still
never create one, so the WuXi rule is intact. It fires exactly once, and 6-APA
now reads 8.4% from Sandoz GmbH, which actually makes it.

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
| `calibrate.py` | isotonic recalibration + the check that it worked |
| `emit.py` | `web/data/risk.json`, graph propagation, the GEO veto |

## Honest limits

- **It predicts FDA-recorded trouble.** Export bans, fires, and a firm quietly
  leaving the US market are in no federal record — `not_modelled` ships inside
  the artifact so the gap is visible next to the number. A news-search layer was
  built and **cut**: it could not move `p12` without destroying the calibration
  that makes the number meaningful, and on the top 8 plants it ran 4 searches
  each and found nothing. It is in this branch's history if anyone wants it.
- **OAI posts months after the inspection ends.** Labels use the END date — when
  the trouble happened, not when the world learned of it. Any lead-time claim has
  to say that.
- **Never report accuracy.** At a 1.7% base rate, "never fails" scores 98%.
- **117–190 positives per cutoff.** Calibration is credible at 5 buckets and
  noise at 10; the finest split the label count supports is what is used.
- **46% is a ceiling, not a maximum.** It is the highest rate ever observed at
  any score, on 61 plants. A plant reading 46% may well be riskier than that —
  the data cannot say by how much, so it does not.
- **Inherited nodes are only as good as the edge.** A product's risk is the risk
  of the plant the graph says makes it. If an edge is wrong, the number is wrong,
  which is why `inherited_from` ships next to every one of them.
