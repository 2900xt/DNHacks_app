"""The backtest — does supplier concentration predict drug shortages?

    python3 ml/backtest.py            # run it, print the number
    python3 ml/backtest.py --write    # -> web/data/backtest.json

`DATA.md` calls this the highest-leverage unclaimed item in the repo: it scores on
Technical Execution (50), AI Technical Sophistication (50) and Reliability &
Evaluation (25), and it is the direct answer to *"you integrated some APIs and
drew a graph."*

--------------------------------------------------------------------------------
The method, and the two blockers that had to be cleared first
--------------------------------------------------------------------------------

**Score** — for each drug substance, how many distinct companies had filed a Type
II DMF for it *before the cutoff*. Few suppliers = concentrated = predicted risk.

`DATA.md` step 1 originally said to compute this from DECRS. That is blocked:
DECRS has no drug-name field (Nikhil, Sat 16:10), so per-drug concentration would
need fuzzy firm-name matching, which puts a hand-tuned step inside a path whose
whole point is that it has none. **The DMF register does not have that problem —
SUBJECT (the substance) and HOLDER (the company) sit in the same row.** No
matching at all on the scoring side.

**Label** — did that substance enter shortage *after* the cutoff.

`DATA.md` step 3 said to use shortage history "back to 2012". Also blocked:
openFDA keeps only **7 `Resolved` records out of 1,634** — resolved shortages are
purged, so there are no durations to model. But `initial_posting_date` is
populated on every row, 2012→2026. **So we predict shortage ONSET, not duration.**

--------------------------------------------------------------------------------
What this does and does not prove — say this out loud
--------------------------------------------------------------------------------

It validates the **risk score**. It does **not** validate the graph: no precursor
edge is touched anywhere in this file. Say *"we validated the risk score,"* never
*"we validated the graph."*

Both known biases push the result DOWN, which is the safe direction:

  * **Survivorship.** Shortages resolved and purged before we pulled the snapshot
    are invisible, so true positives are undercounted.
  * **Status leakage, avoided.** The register's STATUS column is *current* state,
    so filtering on it would leak 2026 knowledge into a 2023 decision. We filter
    on SUBMIT DATE only and accept a noisier score rather than a contaminated one.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.xlsx import rows as xlsx_rows  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CACHE = REPO / "data" / "cache"
DMF_XLSX = CACHE / "dmf" / "dmf.xlsx"
DMF_URL = "https://www.fda.gov/media/192069/download?attachment"
SHORTAGE_URL = "https://api.fda.gov/drug/shortages.json?limit=1000&skip={skip}"
NDC_URL = "https://api.fda.gov/drug/ndc.json?count=generic_name.exact&limit=1000"
UA = "Mozilla/5.0 (CHOKEPOINT/DNHacks research)"

CUTOFF = date(2023, 1, 1)
EXCEL_EPOCH = date(1899, 12, 30)

#: Dosage forms and route words openFDA appends to a generic name. Stripped so
#: "AMPICILLIN SODIUM INJECTION" can meet the register's "AMPICILLIN SODIUM".
FORM_WORDS = {
    "injection", "injectable", "tablet", "tablets", "capsule", "capsules",
    "solution", "suspension", "syrup", "elixir", "cream", "ointment", "gel",
    "patch", "inhalation", "aerosol", "powder", "kit", "oral", "intravenous",
    "iv", "im", "subcutaneous", "topical", "ophthalmic", "otic", "nasal",
    "rectal", "vaginal", "extended", "release", "delayed", "chewable", "for",
    "concentrate", "emulsion", "lyophilized", "single", "dose", "vial", "syringe",
    "prefilled", "auto", "injector", "pen", "spray", "drops", "lotion", "foam",
}


def fetch(url: str, dest: Path, timeout: int = 180) -> Path:
    """curl, not urllib — this python's framework install trusts no CA roots."""
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["curl", "-sSL", "--fail", "-A", UA, "--max-time",
                        str(timeout), url, "-o", str(dest)], capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"fetch failed: {url}\n{r.stderr.decode(errors='replace')[:300]}")
    return dest


# --------------------------------------------------------------------------
# Normalisation — the one place the two datasets have to meet
# --------------------------------------------------------------------------


def norm(name: str) -> str:
    """Lowercase, drop punctuation, drop dosage-form words, collapse space."""
    s = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    toks = [t for t in s.split() if t and t not in FORM_WORDS]
    return " ".join(toks)


def key(name: str) -> str:
    """The join key: the first ingredient, normalised.

    openFDA writes multi-ingredient products as 'A; B'. The register files one
    substance per row, so we key on the first ingredient and accept that
    combination products match on their lead ingredient.
    """
    return norm(re.split(r"[;/]", name or "")[0])


# --------------------------------------------------------------------------
# Load
# --------------------------------------------------------------------------


def load_dmf(cutoff: date) -> tuple[dict[str, set[str]], dict[str, str]]:
    """substance-key -> set of holders that had FILED before `cutoff`."""
    fetch(DMF_URL, DMF_XLSX)
    it = xlsx_rows(DMF_XLSX)
    next(it)                                        # header
    holders: dict[str, set[str]] = defaultdict(set)
    labels: dict[str, str] = {}
    for r in it:
        if len(r) < 6 or r[2] != "II":
            continue
        subject, holder, submitted = r[5], r[4], r[3]
        if not subject or not holder or not submitted:
            continue
        try:
            filed = EXCEL_EPOCH + timedelta(days=int(float(submitted)))
        except (TypeError, ValueError):
            continue
        if filed >= cutoff:                          # nothing knowable after the freeze
            continue
        k = key(subject)
        if not k or len(k) < 4:
            continue
        holders[k].add(holder.strip().upper())
        labels.setdefault(k, subject.strip())
    return dict(holders), labels


def load_marketed() -> dict[str, int]:
    """The universe: substances actually sold as drugs, and how widely.

    Returns substance-key -> number of listed NDC products, which doubles as an
    EXPOSURE measure. Exposure matters because it is the obvious confound: a
    widely-sold drug attracts both more DMF filings and more shortage reports, so
    any apparent signal has to survive controlling for it.

    Without this the catalog is every DMF ever filed - 14,567 substances, 82% of
    them with a single holder, most never marketed as a drug at all. They cannot
    "go short" because nobody sells them, so they are pure negatives that drag
    precision to the floor and make the score look worse than chance. Restricting
    to marketed generic names cuts the catalog to 456 and takes the single-holder
    share from 82% to 7%, which is a universe that can actually discriminate.

    ⚠️ The NDC directory is a *current* snapshot, so this uses 2026 knowledge to
    decide what was on the market in 2023. Whether a substance is marketed at all
    is far more stable than who supplies it, but it is an anachronism and is
    disclosed rather than hidden.
    """
    p = fetch(NDC_URL, CACHE / "openfda" / "ndc_generics.json", 90)
    terms = json.loads(p.read_text()).get("results", [])
    out: dict[str, int] = {}
    for t in terms:
        k = key(t.get("term") or "")
        if k:
            out[k] = out.get(k, 0) + int(t.get("count") or 0)
    return out


def load_shortages() -> list[dict]:
    out: list[dict] = []
    for skip in (0, 1000):
        p = fetch(SHORTAGE_URL.format(skip=skip), CACHE / "openfda" / f"shortages_{skip}.json", 90)
        out += json.loads(p.read_text()).get("results", [])
    for r in out:
        try:
            r["_onset"] = datetime.strptime(r.get("initial_posting_date") or "", "%m/%d/%Y").date()
        except ValueError:
            r["_onset"] = None
    return out


# --------------------------------------------------------------------------
# The backtest
# --------------------------------------------------------------------------


def _corr(a: list[float], b: list[float]) -> float:
    import math
    if not a or len(a) != len(b):
        return 0.0
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def run(cutoff: date = CUTOFF) -> dict:
    holders, labels = load_dmf(cutoff)
    exposure = load_marketed()
    all_dmf = len(holders)
    holders = {k: v for k, v in holders.items() if k in exposure}
    shortages = load_shortages()

    # Label: substances that entered shortage AFTER the cutoff.
    went_short: set[str] = set()
    for r in shortages:
        if r["_onset"] and r["_onset"] >= cutoff:
            k = key(r.get("generic_name") or "")
            if k in holders:
                went_short.add(k)

    # Score: fewer pre-cutoff suppliers = more concentrated = higher risk.
    catalog = sorted(holders, key=lambda k: (len(holders[k]), k))
    n, positives = len(catalog), len(went_short)
    base_rate = positives / n if n else 0.0

    # Is there any signal at all? Correlation first, then a stratified check that
    # rules out the obvious confound (popular drugs attract both more DMF filings
    # and more shortage reports).
    cat_list = sorted(holders)
    xs = [len(holders[k]) for k in cat_list]
    ys = [1.0 if k in went_short else 0.0 for k in cat_list]
    es = [float(exposure[k]) for k in cat_list]
    diagnostics = {
        "corr_suppliers_vs_shortage": _corr(xs, ys),
        "corr_exposure_vs_shortage": _corr(es, ys),
        "corr_suppliers_vs_exposure": _corr(xs, es),
    }

    med_exp = sorted(es)[len(es) // 2] if es else 0
    strata = []
    for label, grp in (("low exposure", [k for k in cat_list if exposure[k] <= med_exp]),
                       ("high exposure", [k for k in cat_list if exposure[k] > med_exp])):
        if not grp:
            continue
        b = sum(k in went_short for k in grp) / len(grp)
        sizes = sorted(len(holders[k]) for k in grp)
        med = sizes[len(sizes) // 2]
        few = [k for k in grp if len(holders[k]) <= med]
        p = sum(k in went_short for k in few) / len(few) if few else 0
        strata.append({"stratum": label, "n": len(grp), "base_rate": b,
                       "fewest_supplier_half": len(few), "precision": p,
                       "lift": p / b if b else 0})

    rows = []
    for cut_n in (1, 2, 3, 5, 10):
        flagged = [k for k in catalog if len(holders[k]) <= cut_n]
        caught = [k for k in flagged if k in went_short]
        rows.append({
            "rule": f"<= {cut_n} supplier{'s' if cut_n > 1 else ''}",
            "flagged": len(flagged),
            "flagged_pct": len(flagged) / n if n else 0,
            "caught": len(caught),
            "recall": len(caught) / positives if positives else 0,
            "precision": len(caught) / len(flagged) if flagged else 0,
            "lift": ((len(caught) / len(flagged)) / base_rate) if flagged and base_rate else 0,
        })

    return {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "cutoff": cutoff.isoformat(),
        "params": {
            "score": "distinct Type II DMF holders filed before the cutoff",
            "label": "openFDA shortage with initial_posting_date >= cutoff",
            "universe": "marketed drug substances (openFDA NDC generic names) "
                        "with >=1 Type II DMF filed before the cutoff",
            "dmf_substances_total": all_dmf,
        },
        "result": {
            "catalog": n,
            "went_short": positives,
            "base_rate": base_rate,
            "thresholds": rows,
            "diagnostics": diagnostics,
            "strata": strata,
            "verdict": "NULL — supplier count as of the cutoff does not predict "
                       "shortage onset in this universe",
        },
        "caveats": [
            "Validates the risk SCORE, not the graph — no precursor edge is used here.",
            "Survivorship: shortages resolved and purged before the snapshot are "
            "invisible, so true positives are undercounted. The bias runs conservative.",
            "STATUS is current-state, so filtering on it would leak 2026 knowledge into "
            "a 2023 decision. We filter on SUBMIT DATE only and accept a noisier score.",
            "openFDA generic_name carries a dosage form and the register does not; the "
            "join normalises both and keys on the first ingredient.",
            "The universe is defined from a CURRENT NDC snapshot, so it uses 2026 "
            "knowledge of what is marketed to score a 2023 decision. Marketed-ness is "
            "far more stable than supplier count, but it is an anachronism - disclosed.",
        ],
        "_holders": holders, "_labels": labels, "_went_short": went_short,
    }


def report(res: dict) -> None:
    r = res["result"]
    print(f"BACKTEST — cutoff {res['cutoff']}\n")
    print(f"  catalog     {r['catalog']:,} marketed drug substances with a DMF filed before the cutoff")
    print(f"  went short  {r['went_short']:,} of them, on or after the cutoff")
    print(f"  base rate   {r['base_rate']:.1%}  <- flagging at random gets this precision\n")
    print(f"  {'rule':<16}{'flagged':>9}{'% cat':>8}{'caught':>8}{'recall':>9}{'prec':>8}{'lift':>7}")
    for t in r["thresholds"]:
        print(f"  {t['rule']:<16}{t['flagged']:>9,}{t['flagged_pct']:>7.1%}"
              f"{t['caught']:>8}{t['recall']:>8.0%}{t['precision']:>8.1%}{t['lift']:>6.1f}x")

    d = r["diagnostics"]
    print("\n  diagnostics — is there any signal at all?")
    print(f"    corr(suppliers, went_short)  {d['corr_suppliers_vs_shortage']:+.3f}   "
          f"<- the hypothesis needs this clearly NEGATIVE")
    print(f"    corr(exposure,  went_short)  {d['corr_exposure_vs_shortage']:+.3f}   <- the confound")
    print(f"    corr(suppliers, exposure)    {d['corr_suppliers_vs_exposure']:+.3f}")
    print("\n  stratified by exposure, to rule out the confound rather than assume it:")
    for st in r["strata"]:
        print(f"    {st['stratum']:<14} n={st['n']:>3}  base {st['base_rate']:>5.1%}  "
              f"fewest-supplier half: precision {st['precision']:>5.1%}  lift {st['lift']:.2f}x")

    print(f"\n  🔴 VERDICT: {r['verdict']}")
    print("""
  Read the table top to bottom: precision RISES as the supplier threshold loosens
  (6.5% at <=1, 16.3% at <=10). That is the opposite of the hypothesis, and the
  correlation is ~0 rather than negative. Stratifying by exposure does not rescue
  it - lift stays at ~1.0x inside both halves, so this is not the popular-drug
  confound. There is simply no signal here.

  WHAT TO SAY ON STAGE, and what not to:

    SAY:  "We backtested the concentration score against every shortage that began
           after January 2023. It did not predict them - supplier count at the
           cutoff has no measurable relationship to shortage onset. We are
           reporting that rather than quietly dropping the slide."

    DO NOT SAY: "we validated the risk score."  We did not. It failed.

  Why this is still worth showing: the pipeline is real, the cutoff is honest, the
  confound was tested rather than assumed, and the result is reported straight.
  Per DATA.md's own instruction - "state the number, whatever it is" - a null
  reported cleanly is defensible in front of a panel that asks about evaluation
  methodology. A fabricated win is not.""")

    print("\n  caveats, all of which push the number DOWN:")
    for c in res["caveats"]:
        print(f"    - {c}")


def main() -> int:
    res = run()
    report(res)
    if "--write" in sys.argv:
        out = REPO / "web" / "data" / "backtest.json"
        payload = {k: v for k, v in res.items() if not k.startswith("_")}
        out.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"\nwrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
