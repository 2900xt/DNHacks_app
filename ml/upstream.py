"""Upstream API sourcing — the closest public proxy, and what it says.

    python3 ml/upstream.py           # build it, test it against shortages

--------------------------------------------------------------------------------
What is actually confidential, and what is not
--------------------------------------------------------------------------------

"Which company supplies the API for drug X" is **not obtainable**. It is
confidential by law, not merely hard:

  * **DMF contents** are confidential commercial information. The *holder list*
    is public; the linkage from a DMF to a finished product is not.
  * **CARES Act § 3112** requires manufacturers to report API source and volume
    annually. FDA has the data. It is not public.
  * **DSCSA / EPCIS** transaction data is restricted to Authorized Trading
    Partners.

So no amount of effort tonight produces true per-drug upstream sourcing. That
gap is the grant ask, and it should be stated as a finding rather than hidden.

--------------------------------------------------------------------------------
What IS recoverable, entirely from public files
--------------------------------------------------------------------------------

Two public registers, joined:

    Type II DMF register   substance -> holder company   (SUBJECT + HOLDER, same row)
    FDA DECRS              firm -> country + `API MANUFACTURE` flag

Join them and you get, per drug substance, **which countries hold the capability
to make its API**. That is not who actually ships it, but it is the country-level
concentration the project's thesis is about, and it is computable with no
hand-curation.

The join is DMF holder name -> DECRS firm name, which is exactly the problem
`entity_resolution.py` exists for. Exact normalized matching gets **23%**.
Blocking on distinctive core tokens and requiring Jaccard >= 0.5 gets **60%** —
the entity resolver more than doubles the usable data.

--------------------------------------------------------------------------------
🔴 The result: upstream concentration does not predict shortage either
--------------------------------------------------------------------------------

    UPSTREAM country HHI      AUC 0.379  p=0.005   anti-predictive
    UPSTREAM few countries    AUC 0.390  p=0.005   anti-predictive
    UPSTREAM CN+IN share      AUC 0.497  p=0.861   NO SIGNAL AT ALL

The third line is the one that matters. "How much of this drug's API capability
sits in China or India" has **literally no relationship** to whether it went
short — 0.497 is a coin flip, and p=0.861 means we cannot reject chance.

**Why this does not sink CHOKEPOINT, and the distinction is real:**

This backtest measures **average marginal risk** — across ~1,300 drugs, does
concentration raise the per-drug probability of a shortage in the next period.

The thesis is about **correlated tail risk** — one precursor failing takes out
six drugs *simultaneously*. That is a different statistical object. A cascade
event is rare, and its signature is covariance between drugs, not an elevated
base rate for any one of them. A marginal-risk backtest cannot see it, and the
2022 Shanghai contrast-dye event is the proof: it was a real single-point
failure that openFDA's shortage list never recorded at all.

**Say:** *"We tested concentration as a marginal predictor and it does not work,
at either layer. Our claim is about correlated failure, which this data cannot
test — there are not enough cascade events in the public record to fit against.
That is the honest limit, and it is what the grant would fund."*

**Do not say:** *"concentration predicts shortage."* We checked. Twice.
"""

from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.entity_resolution import core_tokens, normalize  # noqa: E402
from ml.xlsx import rows as xlsx_rows  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CACHE = REPO / "data" / "cache"
DECRS_ZIP = CACHE / "decrs" / "drls_reg.zip"
DECRS_URL = "https://www.accessdata.fda.gov/cder/drls_reg.zip"
DMF_XLSX = CACHE / "dmf" / "dmf.xlsx"
DMF_URL = "https://www.fda.gov/media/192069/download?attachment"
UA = "Mozilla/5.0 (CHOKEPOINT/DNHacks research)"

EXCEL_EPOCH = date(1899, 12, 30)
MIN_JACCARD = 0.5


def fetch(url: str, dest: Path, timeout: int = 180) -> Path:
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["curl", "-sSL", "--fail", "-A", UA, "--max-time",
                        str(timeout), url, "-o", str(dest)], capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"fetch failed: {url}\n{r.stderr.decode(errors='replace')[:300]}")
    return dest


def api_firms() -> list[tuple[frozenset, str]]:
    """DECRS establishments flagged `API MANUFACTURE`, as (core tokens, country).

    Both FIRM_NAME and REGISTRANT_NAME are indexed: they differ on 33% of rows,
    and a DMF is filed by whichever identity the company chose that year.
    """
    fetch(DECRS_URL, DECRS_ZIP)
    with zipfile.ZipFile(DECRS_ZIP) as z:
        lines = z.read("drls_reg.txt").decode("utf-8", errors="replace").splitlines()
    hdr = [h.strip() for h in lines[0].split("\t")]
    out = []
    for line in lines[1:]:
        r = dict(zip(hdr, [c.strip() for c in line.split("\t")]))
        if "API MANUFACTURE" not in (r.get("OPERATIONS") or ""):
            continue
        iso3 = re.findall(r"\(([A-Z]{3})\)", r.get("ADDRESS") or "")
        if not iso3:
            continue
        for name in (r.get("FIRM_NAME"), r.get("REGISTRANT_NAME")):
            core = core_tokens(normalize(name or ""))
            if core:
                out.append((frozenset(core), iso3[-1]))
    return out


def substances_before(cutoff: date) -> dict[str, set[str]]:
    """substance-key -> holder names, for DMFs filed before the cutoff."""
    from ml.backtest import key
    fetch(DMF_URL, DMF_XLSX)
    it = xlsx_rows(DMF_XLSX)
    next(it)
    subs: dict[str, set[str]] = defaultdict(set)
    for r in it:
        if len(r) < 6 or r[2] != "II" or not (r[3] and r[4] and r[5]):
            continue
        try:
            filed = EXCEL_EPOCH + timedelta(days=int(float(r[3])))
        except (TypeError, ValueError):
            continue
        if filed >= cutoff:
            continue
        k = key(r[5])
        if len(k) >= 4:
            subs[k].add(r[4])
    return dict(subs)


def locate_countries(cutoff: date) -> tuple[dict[str, list[str]], float]:
    """substance -> countries of its API-capable holders, plus the join rate."""
    firms = api_firms()
    index: dict[str, list[int]] = defaultdict(list)
    for i, (core, _) in enumerate(firms):
        for t in core:
            index[t].append(i)

    def where(holder: str) -> str | None:
        core = core_tokens(normalize(holder))
        if not core:
            return None
        counts: Counter = Counter()
        for t in core:
            for i in index.get(t, ()):
                counts[i] += 1
        best = (0.0, None)
        for i, shared in counts.items():
            j = shared / len(core | firms[i][0])
            if j > best[0]:
                best = (j, firms[i][1])
        return best[1] if best[0] >= MIN_JACCARD else None

    subs = substances_before(cutoff)
    located: dict[str, list[str]] = {}
    hits = total = 0
    for s, holders in subs.items():
        cs = []
        for h in holders:
            total += 1
            c = where(h)
            if c:
                cs.append(c)
                hits += 1
        if cs:
            located[s] = cs
    return located, (hits / total if total else 0.0)


def main() -> int:
    from ml.backtest import (MIN_PRODUCTS, auc, market_at, permutation_p,
                             shortages_after)
    cutoff = date(2023, 1, 1)
    located, rate = locate_countries(cutoff)
    print("UPSTREAM API CAPABILITY — DMF holders located via DECRS\n")
    print(f"  DMF holder -> DECRS API firm join: {rate:.0%} "
          f"(exact normalized alone gets 23%; the entity resolver more than doubles it)")
    print(f"  substances with a located API maker: {len(located):,}")

    labelers, _ = market_at(cutoff)
    short = shortages_after(cutoff)
    cat = [g for g in labelers
           if sum(labelers[g].values()) >= MIN_PRODUCTS and g in located]
    y = {g: (1 if g in short else 0) for g in cat}
    print(f"  catalog {len(cat):,} | went short {sum(y.values())} "
          f"| base {sum(y.values()) / len(cat):.1%}\n")

    def hhi(g):
        c = Counter(located[g]); t = sum(c.values())
        return sum((v / t) ** 2 for v in c.values())

    feats = {
        "UPSTREAM country HHI": {g: hhi(g) for g in cat},
        "UPSTREAM few countries": {g: -len(set(located[g])) for g in cat},
        "UPSTREAM CN+IN share of API makers":
            {g: sum(1 for c in located[g] if c in ("CHN", "IND")) / len(located[g])
             for g in cat},
    }
    print(f"  {'feature':<38}{'AUC':>7}{'p':>8}   verdict")
    for n, s in feats.items():
        a = auc(cat, s, y)
        p = permutation_p(cat, s, y, a, n=200)
        v = "predicts" if a > 0.55 else ("anti-predictive" if a < 0.45 else "NO SIGNAL")
        print(f"  {n:<38}{a:>7.3f}{p:>8.3f}   {v}")

    print("""
  🔴 Upstream concentration does not predict shortage either. The CN+IN share -
  the most thesis-aligned measure we can build from public data - is a coin flip.

  This measures AVERAGE MARGINAL risk. The thesis is CORRELATED TAIL risk: one
  precursor failing takes out six drugs at once. Those are different statistical
  objects, and there are not enough cascade events in the public record to fit
  against. The 2022 Shanghai contrast-dye shutdown is the proof - a real
  single-point failure that openFDA's shortage list never recorded at all.""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
