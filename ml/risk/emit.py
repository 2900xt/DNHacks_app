"""Step 7 — score today's plants and write `web/data/risk.json`.

    python3 -m ml.risk.emit            # score + write
    python3 -m ml.risk.emit --news     # + news enrichment (costs API calls)

Trains at the most recent cutoff that still has a full year of outcomes behind it
(inspection data runs to 2026-08-24, so `2025-08-01`), then scores every plant in
the chain **as of today**.

The number on screen is a probability, so two things have to be true and both are
checked in `train.py`: the model beats the simple baselines (it does, at all three
cutoffs), and its probabilities mean something (calibration is monotone at 2 of 3,
and the top bucket lands 5.0-5.6% predicted against 5.4-6.1% observed).

**Evidence lines are generated from the features that actually moved the score**,
not written by hand. If a plant is rated 12% because of two OAIs and a rising
refusal trend, those are the three lines it shows. A number without its reason is
not usable by a procurement officer and not defensible on stage.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ml.risk.features import MODEL_NAMES, History, feature_table  # noqa: E402
from ml.risk.inspections import fei as norm_fei  # noqa: E402
from ml.risk.labels import labeller  # noqa: E402
from ml.risk.model import fit  # noqa: E402
from ml.risk.train import _apply, _standardise_fit  # noqa: E402
from ml.risk.universe import decrs, parse_date  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
TRAIN_CUTOFF = date(2025, 8, 1)
BANDS = [(0.02, "low"), (0.06, "raised"), (1.01, "high")]


def band(p: float) -> str:
    for hi, name in BANDS:
        if p < hi:
            return name
    return "high"


def _plain(f: dict, hist: History, fei: str, today: date,
           contrib: dict[str, float] | None = None) -> list[str]:
    """One line per thing that is true of this plant, in plain words, ORDERED BY
    HOW MUCH IT MOVED THE SCORE.

    Ordering matters more than it looks. Written in template order the lines read
    as a tidy biography and the first one is whatever the template happened to put
    first — for Sandoz that was "no failed FDA inspection on record", while the
    thing actually driving its 6.6% was a paperwork refusal contributing +1.53 to
    the logit, buried third. A user reading top-down would have taken away the
    opposite of what the model believes.

    So each line is tagged with the feature that produced it and sorted by that
    feature's contribution. No acronyms: a supply manager should not need to know
    what OAI means.
    """
    contrib = contrib or {}
    tagged: list[tuple[float, str]] = []

    def add(feature: str, text: str) -> None:
        tagged.append((abs(contrib.get(feature, 0.0)), text))

    out = []
    insp = sorted((d, c) for d, c in hist.insp.get(fei, ()) if d <= today)
    oai = [d for d, c in insp if c == "OAI"]
    vai = [d for d, c in insp if c == "VAI"]
    refu = sorted((d, k) for d, k in hist.refu.get(fei, ()) if d <= today)
    mfg = [d for d, k in refu if k == "mfg"]
    paper = [d for d, k in refu if k == "paperwork"]

    if oai:
        months = int((today - max(oai)).days / 30.4)
        n = len(oai)
        add("oai_all", f"{n} failed FDA inspection{'s' if n > 1 else ''} on record, "
                       f"the most recent {months} months ago")
    elif insp:
        months = int((today - max(d for d, _ in insp)).days / 30.4)
        add("oai_all", f"no failed FDA inspection on record; last inspected "
                       f"{months} months ago")
    else:
        add("oai_all", "no FDA inspection on record")

    recent_vai = [d for d in vai if (today - d).days < 365 * 3]
    if recent_vai:
        add("vai_3y", f"{len(recent_vai)} inspection"
                      f"{'s' if len(recent_vai) > 1 else ''} in the last three years "
                      "found problems short of enforcement")
    recent_mfg = [d for d in mfg if (today - d).days < 365 * 3]
    if recent_mfg:
        add("refusal_mfg_3y", f"{len(recent_mfg)} shipment"
                              f"{'s' if len(recent_mfg) > 1 else ''} refused at the US "
                              "border for manufacturing-quality reasons in three years")
    recent_paper = [d for d in paper if (today - d).days < 365 * 3]
    if recent_paper:
        add("refusal_paper_3y", f"{len(recent_paper)} shipment"
                                f"{'s' if len(recent_paper) > 1 else ''} refused at the "
                                "border on paperwork in three years")
    if f["refusal_trend"] > 0:
        add("refusal_trend", "border refusals are rising year on year")
    elif f["refusal_trend"] < 0:
        add("refusal_trend", "border refusals are falling year on year")
    if not mfg and not paper:
        add("refusal_mfg_3y", "no shipments refused at the US border")

    tagged.sort(key=lambda t: -t[0])
    return [t for _, t in tagged]


def chain_plants() -> dict[str, dict]:
    """Every plant the console can draw, keyed by FEI."""
    out: dict[str, dict] = {}
    rr = REPO / "web" / "data" / "reroute.json"
    if rr.exists():
        doc = json.loads(rr.read_text())
        groups = doc.get("precursors") or doc.get("nodes") or {}
        for p in (groups.values() if isinstance(groups, dict) else groups):
            for h in p.get("holders", p.get("alternates", [])):
                for f in h.get("feis", []):
                    k = norm_fei(f)
                    if k:
                        out.setdefault(k, {"fei": k, "node_id": h.get("node_id"),
                                           "label": h.get("matched_firm") or h.get("holder"),
                                           "country": (h.get("countries") or [None])[0]})
    sites = REPO / "web" / "data" / "nodes.sites.json"
    if sites.exists():
        for n in json.loads(sites.read_text()):
            k = norm_fei((n.get("attrs") or {}).get("fei"))
            if k:
                out.setdefault(k, {"fei": k, "node_id": n["id"], "label": n.get("label"),
                                   "country": n.get("country")})
                out[k]["site_id"] = n["id"]
    return out


def main() -> int:
    today = date.today()
    hist = History()

    # Fit at the last cutoff with a full year of outcomes behind it.
    feis, rows, uni = feature_table(TRAIN_CUTOFF, hist)
    lab = labeller(hist)
    Y = [float(lab(f, TRAIN_CUTOFF)) for f in feis]
    X = [[r[n] for n in MODEL_NAMES] for r in rows]
    mu, sd = _standardise_fit(X)
    predict, w, iters = fit(_apply(X, mu, sd), Y, l2=10.0)
    print(f"  trained at {TRAIN_CUTOFF}: {len(feis):,} plants, {int(sum(Y))} positives, "
          f"{iters} iterations")

    reg = decrs()
    plants = chain_plants()
    print(f"  scoring {len(plants)} chain plants as of {today}")

    scored: dict[str, dict] = {}
    for k, meta in sorted(plants.items()):
        country = meta.get("country") or ""
        if len(country) == 3:                       # reroute uses ISO3, features want ISO2
            from ml.risk.universe import _ISO3_TO_2
            country = _ISO3_TO_2.get(country, "")
        f = hist.features(k, today, country)
        z = predict(_apply([[f[n] for n in MODEL_NAMES]], mu, sd)[0])
        p = 1 / (1 + math.exp(-max(-30, min(30, z))))
        # Per-feature contribution to the logit, so the evidence can be ordered by
        # what actually moved the number rather than by template order.
        contrib = {n: ((f[n] - mu[i]) / sd[i]) * w[i + 1]
                   for i, n in enumerate(MODEL_NAMES)}
        rec = {
            "fei": k, "label": meta.get("label") or reg.get(k, {}).get("firm") or k,
            "country": country or None,
            "p12": round(p, 4), "band": band(p),
            "evidence": _plain(f, hist, k, today, contrib),
            "drivers": {n: round(c, 3) for n, c in
                        sorted(contrib.items(), key=lambda t: -abs(t[1]))[:3]},
            "features": {n: round(f[n], 4) for n in MODEL_NAMES},
        }
        node = meta.get("node_id")
        if node:
            # A company with several plants takes the worst of them: a buyer is
            # exposed to the weakest site, not the average one.
            prev = scored.get(node)
            if not prev or p > prev["p12"]:
                scored[node] = {**rec, "node_id": node}
        scored[f"facility:fei:{k}"] = {**rec, "node_id": f"facility:fei:{k}"}

    doc = {
        "run_at": today.isoformat(),
        "rule": "next-failure-v1",
        "rule_text": ("Logistic model on nine features of a plant's FDA inspection and "
                      "import-refusal history at a cutoff, trained on every actively "
                      "inspected drug establishment; predicts a failed inspection or a "
                      "manufacturing import refusal in the following 12 months."),
        "horizon_days": 365,
        "trained_at": TRAIN_CUTOFF.isoformat(),
        "bands": {"low": "<2%", "raised": "2–6%", "high": ">6%"},
        "model": {"features": MODEL_NAMES, "intercept": w[0],
                  "coefficients": dict(zip(MODEL_NAMES, w[1:])),
                  "standardisation": {n: {"mu": mu[i], "sd": sd[i]}
                                      for i, n in enumerate(MODEL_NAMES)}},
        "not_modelled": [
            "export bans and trade actions",
            "fires, floods and other physical loss",
            "a firm quietly leaving the US market",
            "anything not in an FDA record — public records lag events by months",
        ],
        "plants": scored,
    }
    out = REPO / "web" / "data" / "risk.json"
    out.write_text(json.dumps(doc, indent=2) + "\n")

    ranked = sorted({v["fei"]: v for v in scored.values()}.values(),
                    key=lambda r: -r["p12"])
    print(f"\n  {'plant':<44}{'p12':>7}  band     why")
    for r in ranked[:10]:
        print(f"  {(r['label'] or '')[:42]:<44}{r['p12']*100:>6.1f}%  {r['band']:<8} {r['evidence'][0][:52]}")
    print(f"\n  wrote {out.relative_to(REPO)} — {len(scored)} keys, "
          f"{len({v['fei'] for v in scored.values()})} distinct plants")
    return 0


if __name__ == "__main__":
    sys.exit(main())
