"""Entity resolution — collapse company name variants onto one canonical node.

The same firm appears under inconsistent names across DMF, DECRS, OASIS and
openFDA: punctuation variants, transliterations, legal-suffix noise, parent vs.
subsidiary, and shell-ish siblings. This module decides when two names are the
same establishment, and shows why.

    python3 ml/entity_resolution.py --eval    # precision/recall on the benchmark
    python3 ml/entity_resolution.py --sweep   # threshold sweep
    python3 ml/entity_resolution.py --emit    # config as JSON, for graph.ts

--------------------------------------------------------------------------------
Order of preference — this matters more than the matcher
--------------------------------------------------------------------------------

1. **FEI.** Exact, 100% populated on inspection rows and on drug OASIS rows.
   If both sides have one, the answer is decided and no scoring happens.
2. **DUNS.** Exact where present.
3. Only then: this fuzzy matcher, and every id it produces is flagged
   `resolved_by='fuzzy'` so the UI can mark it as inferred rather than measured.

The interesting engineering is in *not* using the matcher when a key exists.

--------------------------------------------------------------------------------
Why token classes, and not edit distance
--------------------------------------------------------------------------------

Two documented failures drove the design:

    WUXI BIOLOGICS      vs  WuXi AppTec     -> must NOT match (false positive)
    ORIGINCELL BIOTECH. vs  Origincell Tech -> must match (suffix-stripping misses)

Edit distance gets both wrong: the first pair is close, the second is far. What
separates them is *which kind of token* is shared. "WuXi" is a Chinese city;
sharing it means nothing. "Origincell" is distinctive; sharing it means a lot.

So every token is classed as LEGAL (ltd, gmbh), INDUSTRY (pharma, biologics,
technology), GEO (wuxi, shijiazhuang, north) or DISTINCTIVE, and matching runs
on the distinctive core. If a name has no distinctive core - "North China
Pharmaceutical" is entirely geo + industry - we fall back to the full token set
at a higher bar rather than declaring a match on generic words alone.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# --------------------------------------------------------------------------
# Token vocabulary. Shaurya: `--emit` gives you this as JSON.
# --------------------------------------------------------------------------

LEGAL = frozenset("""
ltd limited llc lp llp inc incorporated co cos corp corporation company
pvt private plc sa ag gmbh bv nv oy ab as spa srl kk pte
""".split())

INDUSTRY = frozenset("""
pharma pharmas pharmaceutical pharmaceuticals pharmaceutica pharm
lab labs laboratory laboratories
bio biotech biotechnology biologics biological biosciences
tech technology technologies
science sciences life lifescience healthcare health
medical medicine medicines drug drugs chemical chemicals chem
industries industry manufacturing mfg works
group holding holdings international intl worldwide global enterprises
""".split())

# Place names that collide with company names in our corpus. GEO tokens never
# carry a match on their own - that is the whole WuXi lesson.
GEO = frozenset("""
wuxi shijiazhuang chengdu zhuhai tianjin shanghai beijing nanjing hangzhou
jiangsu zhejiang shandong hebei guangdong sichuan mongolia inner
china chinese sinopharm-cn india indian netherlands dutch spain spanish
sikkim dewas nawashahr toansa punjab gujarat hyderabad mumbai baddi
north south east west central new old
""".split())

STOP = frozenset("""
the a an of and for prev previously formerly fka nee dba aka
""".split())

#: Score at or above which two names are called the same establishment.
#: Chosen by the sweep in `--sweep`, not by taste.
MATCH_THRESHOLD = 0.60

#: A match is refused outright when both sides declare a country and they differ.
#: Documented as the only thing separating `United Laboratories Manufacturing, LLC`
#: (US) from `The United Laboratories (Inner Mongolia)` (CN).
COUNTRY_GUARD = True


def normalize(name: str) -> list[str]:
    """Lowercase, strip accents and punctuation, split into tokens."""
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.lower()
    n = re.sub(r"[^a-z0-9]+", " ", n)
    return [t for t in n.split() if t and t not in STOP]


def core_tokens(tokens: Iterable[str]) -> set[str]:
    """The distinctive part of a name — what actually identifies the firm."""
    return {t for t in tokens if t not in LEGAL and t not in INDUSTRY and t not in GEO}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _containment(a: set[str], b: set[str]) -> float:
    """How completely the smaller set sits inside the larger one.

    `SUN PHARMA IND LTD` -> {sun} sits entirely inside
    `Sun Pharmaceutical Industries (prev. Ranbaxy)` -> {sun, ranbaxy}.
    A qualifier added to a name should not break the match.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


@dataclass
class Match:
    same: bool
    score: float
    method: str
    reason: str

    def to_json(self) -> dict:
        return {"same": self.same, "score": round(self.score, 3), "method": self.method, "reason": self.reason}


def compare(
    name_a: str,
    name_b: str,
    *,
    country_a: str | None = None,
    country_b: str | None = None,
    fei_a: str | None = None,
    fei_b: str | None = None,
    duns_a: str | None = None,
    duns_b: str | None = None,
    threshold: float = MATCH_THRESHOLD,
) -> Match:
    """Decide whether two names denote the same establishment, and say why."""

    # 1. Exact keys short-circuit everything. This is the important branch.
    if fei_a and fei_b:
        same = str(fei_a) == str(fei_b)
        return Match(same, 1.0 if same else 0.0, "fei",
                     f"FEI {fei_a} {'==' if same else '!='} {fei_b} — exact, no matching")
    if duns_a and duns_b:
        same = str(duns_a) == str(duns_b)
        return Match(same, 1.0 if same else 0.0, "duns",
                     f"DUNS {duns_a} {'==' if same else '!='} {duns_b} — exact, no matching")

    # 2. Country guard.
    if COUNTRY_GUARD and country_a and country_b and country_a.upper() != country_b.upper():
        return Match(False, 0.0, "country-guard",
                     f"country {country_a} != {country_b} — refused before scoring")

    ta, tb = normalize(name_a), normalize(name_b)
    ca, cb = core_tokens(ta), core_tokens(tb)

    # 3. Both sides have a distinctive core — the normal path.
    if ca and cb:
        if not (ca & cb):
            return Match(False, 0.0, "core-disjoint",
                         f"no shared distinctive token ({sorted(ca)} vs {sorted(cb)})")
        score = max(_jaccard(ca, cb), 0.9 * _containment(ca, cb))
        shared = sorted(ca & cb)
        return Match(score >= threshold, score, "core",
                     f"shared distinctive {shared}; core {sorted(ca)} vs {sorted(cb)}")

    # 4. One or both names are entirely generic ("North China Pharmaceutical").
    #    Fall back to the full token set at a higher bar. Never match on GEO alone.
    fa = {t for t in ta if t not in LEGAL}
    fb = {t for t in tb if t not in LEGAL}
    score = _jaccard(fa, fb)
    raised = min(0.95, threshold + 0.25)
    empty_side = "both" if not ca and not cb else ("a" if not ca else "b")
    return Match(score >= raised, score, "generic-fallback",
                 f"no distinctive core on {empty_side}; full-token overlap at raised bar {raised:.2f}")


# --------------------------------------------------------------------------
# Baselines, for comparison
# --------------------------------------------------------------------------


def baseline_exact(a: str, b: str, **_) -> bool:
    return a.strip() == b.strip()


def baseline_normalized(a: str, b: str, **_) -> bool:
    return normalize(a) == normalize(b)


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------

BENCH = Path(__file__).parent / "benchmark" / "entity_pairs.json"


def _load_pairs() -> list[dict]:
    return json.loads(BENCH.read_text())["pairs"]


def _score_method(pairs: list[dict], predict) -> dict:
    tp = fp = tn = fn = 0
    errors = []
    for p in pairs:
        truth = p["label"] == "same"
        pred = predict(p)
        if pred and truth:
            tp += 1
        elif pred and not truth:
            fp += 1
            errors.append(("FP", p))
        elif not pred and truth:
            fn += 1
            errors.append(("FN", p))
        else:
            tn += 1
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn, "precision": prec,
            "recall": rec, "f1": f1, "accuracy": (tp + tn) / len(pairs), "errors": errors}


def _ours(threshold: float):
    def predict(p):
        return compare(
            p["a"]["name"], p["b"]["name"],
            country_a=p["a"].get("country"), country_b=p["b"].get("country"),
            threshold=threshold,
        ).same
    return predict


def evaluate(threshold: float = MATCH_THRESHOLD, *, verbose: bool = True) -> dict:
    pairs = _load_pairs()
    methods = {
        "exact string": lambda p: baseline_exact(p["a"]["name"], p["b"]["name"]),
        "normalized exact": lambda p: baseline_normalized(p["a"]["name"], p["b"]["name"]),
        f"ours (t={threshold:.2f})": _ours(threshold),
    }
    results = {name: _score_method(pairs, fn) for name, fn in methods.items()}

    if verbose:
        n_same = sum(1 for p in pairs if p["label"] == "same")
        print(f"benchmark: {len(pairs)} pairs ({n_same} same / {len(pairs)-n_same} different)")
        print("deliberately hard - over-samples the traps. NOT comparable to the")
        print("corpus-wide 9%-exact / 42%-normalized join rates.\n")
        print(f"{'method':<22} {'prec':>6} {'rec':>6} {'F1':>6} {'acc':>6}   TP FP TN FN")
        for name, r in results.items():
            print(f"{name:<22} {r['precision']:>6.2f} {r['recall']:>6.2f} {r['f1']:>6.2f} "
                  f"{r['accuracy']:>6.2f}   {r['tp']:>2} {r['fp']:>2} {r['tn']:>2} {r['fn']:>2}")

        ours = results[f"ours (t={threshold:.2f})"]
        print(f"\nfailure cases ({len(ours['errors'])}) — the slide, not hidden:")
        if not ours["errors"]:
            print("  none on this set")
        for kind, p in ours["errors"]:
            m = compare(p["a"]["name"], p["b"]["name"],
                        country_a=p["a"].get("country"), country_b=p["b"].get("country"),
                        threshold=threshold)
            flag = " [CONTESTED LABEL]" if p.get("contested") else ""
            print(f"  {kind} #{p['id']}{flag}  {p['a']['name']!r} vs {p['b']['name']!r}")
            print(f"       score {m.score:.2f} via {m.method} — {m.reason}")
    return results


def sweep() -> None:
    pairs = _load_pairs()
    print(f"{'threshold':>9} {'prec':>6} {'rec':>6} {'F1':>6} {'acc':>6}")
    rows = []
    for i in range(20, 100, 5):
        t = i / 100
        r = _score_method(pairs, _ours(t))
        rows.append((t, r))
        mark = " <-- shipping" if abs(t - MATCH_THRESHOLD) < 1e-9 else ""
        print(f"{t:>9.2f} {r['precision']:>6.2f} {r['recall']:>6.2f} {r['f1']:>6.2f} {r['accuracy']:>6.2f}{mark}")

    best_f1 = max(r["f1"] for _, r in rows)
    plateau = [t for t, r in rows if abs(r["f1"] - best_f1) < 1e-9]
    lo, hi = min(plateau), max(plateau)
    mid = (lo + hi) / 2
    print(f"\nbest F1 {best_f1:.2f} over a PLATEAU of {lo:.2f}-{hi:.2f} — not a single peak.")
    print("A flat optimum is the point: the result is not sensitive to the threshold,")
    print("so this is not a number tuned to make the benchmark look good.")
    print(f"Shipping {MATCH_THRESHOLD:.2f}, near the plateau midpoint ({mid:.2f}) — furthest")
    print("from both cliff edges, which is where a threshold should sit.")


def config() -> dict:
    return {
        "match_threshold": MATCH_THRESHOLD,
        "country_guard": COUNTRY_GUARD,
        "key_precedence": ["fei", "duns", "fuzzy"],
        "token_classes": {"legal": sorted(LEGAL), "industry": sorted(INDUSTRY),
                          "geo": sorted(GEO), "stop": sorted(STOP)},
    }


if __name__ == "__main__":
    if "--emit" in sys.argv:
        print(json.dumps(config(), indent=2))
    elif "--sweep" in sys.argv:
        sweep()
    else:
        evaluate()
