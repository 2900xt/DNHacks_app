# Entity resolution — measured results and the failure slide

> Run `python3 ml/entity_resolution.py` to reproduce every number here.
> Benchmark: `entity_pairs.json`, 20 labeled pairs, 10 same / 10 different.

## The numbers

| Method | Precision | Recall | F1 | Accuracy |
|---|---:|---:|---:|---:|
| Exact string | 0.00 | 0.00 | 0.00 | 0.50 |
| Normalized exact (lowercase, strip punctuation) | 1.00 | 0.10 | 0.18 | 0.55 |
| **Ours — token-class matching + country guard** | **0.90** | **0.90** | **0.90** | **0.90** |

❗ **State the population or the number is meaningless.** This benchmark is
*deliberately hard* — it over-samples the exact collisions that break naive matching.
It is **not** comparable to the corpus-wide **9% exact / 42% normalized** join rates in
the brief, which were measured across all DMF/DECRS names. Two different populations.
Quote them separately, never as a before/after.

## Why the threshold is not fitted

F1 is **flat at 0.90 across thresholds 0.50–0.90** — a plateau, not a peak. That is the
point: the result does not depend on the threshold, so it is not a number chosen to
flatter the benchmark. We ship **0.60**, near the plateau midpoint, furthest from both
cliff edges.

```
threshold   prec    rec     F1    acc
     0.45   0.77   1.00   0.87   0.85
     0.50   0.90   0.90   0.90   0.90
     0.60   0.90   0.90   0.90   0.90  <-- shipping
     0.90   0.90   0.90   0.90   0.90
     0.95   0.89   0.80   0.84   0.85
```

## Ablation — what the country guard is actually worth

`python3 ml/entity_resolution.py --ablate`

| Config | Precision | Recall | F1 | Accuracy | False positives |
|---|---:|---:|---:|---:|---|
| With country guard | **0.90** | 0.90 | **0.90** | 0.90 | #17 |
| **Without** country guard | **0.75** | 0.90 | 0.82 | 0.80 | #13, #17, #18 |

❗ **The guard carries 0.15 of the precision.** Pairs #13 (`United Laboratories
Manufacturing, LLC` 🇺🇸 vs `The United Laboratories (Inner Mongolia)` 🇨🇳) and #18
(`Centrient Pharmaceuticals Netherlands B.V.` vs `Centrient Pharmaceuticals India`) have
**identical token cores** — `{united}` and `{centrient}`. Nothing in the *name* separates
them. Only the country does.

**So the honest number depends on coverage:** wherever country is missing, expect
precision nearer **0.75** than 0.90. Say that before someone asks.

## 🔴 The failure slide — 2 of 20, not hidden

### FN #3 — `Sun Pharmaceutical Industries (prev. Ranbaxy)` vs `SUN PHARMA IND LTD`
Scored **0.45**, needed 0.60. Cores are `{ranbaxy, sun}` vs `{ind, sun}`.

**Cause, named:** `IND` is an abbreviation of *Industries* and is missing from the
INDUSTRY vocabulary, so it survives as a false distinctive token and dilutes the score.

**We have not patched it, deliberately.** The fix is one word in a set — but adding it
*after seeing it fail on the test set* is tuning on test, and we would rather report 0.90
honestly than 0.95 with a quiet edit. It is logged as a known fix, applied only when the
vocabulary is next revised for reasons other than this pair.

### FP #17 — `UNITED LABORATORIES CHENGDU` vs `The United Laboratories (Inner Mongolia)`
Scored **1.00**. Both cores reduce to `{united}` after removing geography (`chengdu`,
`inner mongolia`) and industry (`laboratories`). Same country, so the guard does not fire.

**This one is genuinely hard, and the label is contested.** They are two sites of one
corporate parent. We label them *different* because the graph resolves to **facilities**;
someone modelling corporate parents would label them *same*. The honest framing on stage:
*"our matcher cannot separate two plants of the same company from one plant named two
ways — and neither can the public data, because there is no site-level identifier in the
DMF list."* This is exactly where **FEI earns its keep** — both sites have distinct FEIs,
so in production this pair never reaches the fuzzy matcher at all.

## What actually does the work

**Not the matcher — the key precedence.** FEI first (exact, 100% populated on inspection
and drug-refusal rows), DUNS second, fuzzy only as a last resort, and every fuzzy id is
flagged `resolved_by='fuzzy'` so the UI can mark it as inferred rather than measured.

The matcher exists for the rows with no key. Its design comes from two documented cases:

| Pair | Naive edit distance | Ours | Why |
|---|---|---|---|
| `WUXI BIOLOGICS` vs `WuXi AppTec` | close → **wrong match** | correctly rejected | `wuxi` is a Chinese *city*; sharing it means nothing |
| `ORIGINCELL BIOTECHNOLOGY` vs `Origincell Technology` | far → **wrong miss** | correctly matched | `origincell` is distinctive; the differing token is industry noise |

Edit distance gets both backwards. What separates them is *which class of token* is
shared, which is why matching runs on the distinctive core rather than the whole string.

## Known limits — say these before a judge finds them

- ⚠️ **10–20% false positives on two-token Chinese names even with a country guard**
  (measured on OASIS `LGL_NAME`, documented in the OASIS deep-dive). This benchmark's
  0.90 precision is on a curated set; the corpus rate is worse.
- ⚠️ **The country guard is doing real work.** Pair #13 (`United Laboratories
  Manufacturing, LLC` US vs `The United Laboratories (Inner Mongolia)` CN) matches on
  tokens alone and is only separated by country. Where country is missing, that
  protection is gone.
- ⚠️ **GEO is a hand-built list**, not a gazetteer. It covers the place names that collide
  in *our* corpus. A new source with new geography needs it extended.
- ⚠️ **Two of twenty labels are contested** (#17, #18 — sites of one parent, and parent vs
  subsidiary). They are flagged in the data so a reader can disagree with the label rather
  than with the score.
- ❌ **No corporate-ownership resolution.** The stretch goal — do the "5 Chinese 6-APA
  companies" collapse to fewer ultimate owners — is not attempted here.
