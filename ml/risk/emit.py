"""Step 7 — score today's plants and write `web/data/risk.json`.

    python3 -m ml.risk.emit            # score + write

Trains at the most recent cutoff that still has a full year of outcomes behind it
(inspection data runs to 2026-08-24, so `2025-08-01`), then scores every plant in
the chain **as of today**.

The number on screen is a probability, so two things have to be true: the model
beats the simple baselines (it does, at all three cutoffs - `train.py`), and its
probabilities mean something. The raw logistic score does NOT: out of fold it
reached 100% for a group whose observed rate was 36%. So the score is passed
through an isotonic curve fitted on out-of-fold predictions (`calibrate.py`),
which cannot reorder anything and makes every band land inside the 95% interval
of what was actually observed.

Nodes that are not places - products, APIs, drugs, precursors - have no FDA record
of their own and inherit the risk of the worst plant behind them, so all 1,706
resolvable nodes the UI can draw carry a number rather than only the 925 plants.

**Evidence lines are generated from the features that actually moved the score**,
not written by hand. If a plant is rated 12% because of two OAIs and a rising
refusal trend, those are the three lines it shows. A number without its reason is
not usable by a procurement officer and not defensible on stage.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ml.risk.features import MODEL_NAMES, History, feature_table  # noqa: E402
from ml.risk.inspections import fei as norm_fei  # noqa: E402
from ml.risk.labels import labeller  # noqa: E402
from ml.risk.model import fit  # noqa: E402
from ml.risk.calibrate import apply_isotonic, fit_isotonic, interval, wilson  # noqa: E402
from ml.risk.train import _apply, _standardise_fit, cross_val  # noqa: E402
from ml.risk.universe import decrs, parse_date  # noqa: E402
from ml.entity_resolution import GEO, core_tokens, normalize  # noqa: E402

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


def chain_plants() -> dict[str, list[dict]]:
    """node_id -> the FEIs behind it, for EVERY node the console can draw.

    Three sources, because a node reaches its plants three different ways:

      1. `nodes.*.json` `attrs.fei` — facility and site nodes carry their own.
      2. `reroute.json` holders — AEGIS already resolved DMF holders to DECRS
         establishments, so reuse that rather than repeat the matching.
      3. DECRS name matching — `company:name:*` nodes have NO fei anywhere, and
         they are what the globe actually draws. Resolved through
         `entity_resolution`'s distinctive-token core with the SAME ambiguity
         refusal AEGIS uses: if two firms tie, the company gets no score rather
         than another plant's history.

    A company with several plants is returned with all of them; the caller takes
    the worst, because a buyer is exposed to the weakest site and not the average.
    """
    out: dict[str, list[dict]] = defaultdict(list)

    def add(node_id, fei, label, country):
        k = norm_fei(fei)
        if node_id and k and not any(r["fei"] == k for r in out[node_id]):
            out[node_id].append({"fei": k, "label": label, "country": country})

    # 1. every node file that carries an FEI
    for f in sorted((REPO / "web" / "data").glob("nodes.*.json")):
        for n in json.loads(f.read_text()):
            fei_attr = (n.get("attrs") or {}).get("fei")
            if fei_attr:
                add(n["id"], fei_attr, n.get("label"), n.get("country"))

    # 2. AEGIS holders — already resolved, do not redo the work
    rr = REPO / "web" / "data" / "reroute.json"
    if rr.exists():
        doc = json.loads(rr.read_text())
        groups = doc.get("precursors") or doc.get("nodes") or {}
        for p in (groups.values() if isinstance(groups, dict) else groups):
            for h in p.get("holders", p.get("alternates", [])):
                for fv in h.get("feis", []):
                    add(h.get("node_id"), fv, h.get("matched_firm") or h.get("holder"),
                        (h.get("countries") or [None])[0])

    # 3. company:name:* nodes with no FEI anywhere — resolve against DECRS
    reg_by_core: dict[frozenset, list[tuple[str, dict]]] = defaultdict(list)
    for f, rec in decrs().items():
        core = frozenset(core_tokens(normalize(rec.get("firm") or "")))
        if core:
            reg_by_core[core].append((f, rec))

    unresolved = geo_vetoed = 0
    for f in sorted((REPO / "web" / "data").glob("nodes.*.json")):
        for n in json.loads(f.read_text()):
            if n["type"] != "company" or out.get(n["id"]):
                continue
            label = n.get("label") or n["id"].rsplit(":", 1)[1].replace("-", " ")
            want = core_tokens(normalize(label))
            if not want:
                continue
            scored = sorted(((len(want & c) / len(want | c), c) for c in reg_by_core),
                            key=lambda t: -t[0])
            if not scored or scored[0][0] < 0.5:
                unresolved += 1
                continue
            top = scored[0][0]
            if len([1 for sc, _ in scored if top - sc < 0.05]) > 1:
                unresolved += 1        # ambiguous: refuse, exactly as AEGIS does
                continue
            # GEO guard. `core_tokens` strips place names by design — that is the
            # WuXi lesson — but stripping them makes "UNITED LABORATORIES CHENGDU"
            # and "Zhuhai United Laboratories" the identical core {united,
            # laboratories} and a perfect 1.00 match. They are different plants in
            # different cities, and the curated node says so in its own attrs:
            # "DECRS carries TUL Inner Mongolia and Zhuhai, not the Chengdu site".
            # Unguarded, 6-APA — the headline chokepoint — inherited four failed
            # inspections belonging to a plant 1,500 km away.
            #
            # GEO still cannot CREATE a match; it can only VETO one, which keeps
            # the WuXi rule intact.
            want_geo = {t for t in normalize(label) if t in GEO}
            keep = []
            for fei_v, rec in reg_by_core[scored[0][1]]:
                cand_geo = {t for t in normalize(rec.get("firm") or "") if t in GEO}
                if want_geo and cand_geo and not (want_geo & cand_geo):
                    continue
                keep.append((fei_v, rec))
            if not keep:
                geo_vetoed += 1
                unresolved += 1
                continue
            for fei_v, rec in keep:
                add(n["id"], fei_v, rec.get("firm") or label, None)
    if unresolved:
        print(f"  {unresolved} company node(s) unresolved or ambiguous — no score, "
              f"by design ({geo_vetoed} vetoed for naming a different city)")
    return dict(out)


#: Which way risk travels along each relation. A plant's trouble reaches the drug
#: it makes, then the product that drug is sold as — so `drug -produced_by->
#: facility` has to be walked BACKWARDS (the producer is the source of risk, and
#: `produced_by` points at the producer). Every other relation already points
#: downstream.
REVERSED = {"produced_by"}


def propagate(scored: dict[str, dict], nodes: set[str]) -> int:
    """Give every reachable node the risk of the worst plant behind it.

    Direct scoring covers facilities and the companies we can resolve — 926 of
    the 1,732 nodes the UI can draw. The other 806 are products, APIs, drugs and
    precursors, which have no FDA record of their own because they are not
    places. Their risk is entirely the risk of whoever makes them, which is what
    a supply-chain view is for: a buyer looking at an NDC wants to know that the
    only plant making it is in trouble.

    Worst-case, not average, for the same reason the per-node rule is worst-site:
    a second healthy supplier does not fix the first one's shutdown unless it can
    absorb the volume, and nothing in these files says whether it can.
    """
    edges = []
    for f in sorted((REPO / "web" / "data").glob("edges.*.json")):
        for e in json.loads(f.read_text()):
            src, dst, rel = e.get("src"), e.get("dst"), e.get("rel", "")
            if not src or not dst:
                continue
            edges.append((dst, src) if rel in REVERSED else (src, dst))

    out = defaultdict(list)
    for a, b in edges:
        out[a].append(b)

    # Relax until nothing changes. Bounded by node count so a cycle in the graph
    # (company -hosts-> facility -operated_by-> company is a real one) terminates
    # instead of spinning.
    # How many distinct plants sit upstream of each node. `api:ampicillin` has
    # ten; `api:dicloxacillin-sodium` has one. The propagated p12 is the WORST of
    # them, which answers "will one of this node's suppliers hit trouble" — not
    # "will this node run out". Those are different questions and the second one
    # needs volumes nobody in this repo has, so ship the supplier count next to
    # the number and let the reader see the difference: 46% behind one plant is a
    # shortage, 46% behind fifty-two is a Tuesday.
    behind = defaultdict(set)
    for src, dsts in out.items():
        if src.startswith(("facility:", "company:")):
            for d in dsts:
                behind[d].add(src)
    for _ in range(len(nodes) + 1):
        grew = False
        for src, dsts in out.items():
            for d in dsts:
                if behind[src] - behind[d]:
                    behind[d] |= behind[src]
                    grew = True
        if not grew:
            break

    added = 0
    for _ in range(len(nodes) + 1):
        changed = False
        for src in list(out):
            base = scored.get(src)
            if not base:
                continue
            for dst in out[src]:
                if dst not in nodes:
                    continue
                cur = scored.get(dst)
                if cur and not cur.get("inherited_from"):
                    continue                      # a real score outranks a hop
                if cur and cur["p12"] >= base["p12"]:
                    continue
                origin = base.get("inherited_from") or src
                # Strip any preamble the parent already carries: on a two-hop
                # inherit (facility → drug → product) the line would otherwise
                # appear twice, once for each hop.
                why = [e for e in base["evidence"]
                       if not e.startswith("No FDA record of its own")
                       and "sit upstream of this" not in e]
                scored[dst] = {**base, "node_id": dst,
                               "basis": "inherited",
                               "inherited_from": origin,
                               "inherited_via": src,
                               "upstream_plants": len(behind.get(dst) or ()),
                               "evidence": [f"No FDA record of its own — this is "
                                            f"the risk of {base['label']}, which "
                                            f"makes it."] + why[:2]}
                n_up = len(behind.get(dst) or ())
                if n_up > 1:
                    scored[dst]["evidence"].insert(
                        1, f"{n_up} plants sit upstream of this — the figure is the "
                           f"most at-risk of them, not the chance all {n_up} fail "
                           f"at once.")
                if not cur:
                    added += 1
                changed = True
        if not changed:
            break
    return added


def ui_nodes() -> set[str]:
    ids = set()
    for f in (REPO / "web" / "data").glob("nodes.*.json"):
        for n in json.loads(f.read_text()):
            if isinstance(n, dict) and n.get("id"):
                ids.add(n["id"])
    return ids


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

    # The raw logit ranks well and lies about magnitude: out of fold it reaches
    # 99.99% for plants whose actual event rate is 36%. Recalibrate on OUT-OF-FOLD
    # scores — fitting on in-sample scores would calibrate to answers already seen.
    oof = cross_val(X, Y, lambda Xt, Yt: fit(Xt, Yt, l2=10.0))
    cal = fit_isotonic(oof, [int(y) for y in Y])
    print(f"  calibrated on {len(oof):,} out-of-fold scores: {len(cal)} monotone "
          f"blocks, {cal[0]['p']*100:.2f}% → {cal[-1]['p']*100:.1f}% "
          f"(top block n={cal[-1]['n']})")

    reg = decrs()
    nodes_to_plants = chain_plants()
    n_feis = len({r["fei"] for v in nodes_to_plants.values() for r in v})
    print(f"  scoring {len(nodes_to_plants)} nodes / {n_feis} distinct plants as of {today}")

    scored: dict[str, dict] = {}
    no_history = 0

    def score_one(fei_key: str, label: str, country: str) -> dict:
        # reroute.json supplies country codes lower-cased, and in ISO3 for some
        # rows. Without the .upper() the comparison in features.py is against
        # "CN"/"IN", so `country_cn` and `country_in` silently stayed 0 for every
        # plant that reached us through a reroute — a feature that never fires is
        # worse than an absent one, because it looks like evidence of safety.
        country = (country or "").upper()
        if len(country) == 3:
            from ml.risk.universe import _ISO3_TO_2
            country = _ISO3_TO_2.get(country, "")
        f = hist.features(fei_key, today, country)
        z = predict(_apply([[f[n] for n in MODEL_NAMES]], mu, sd)[0])
        # Calibrated, not sigmoid(z). The isotonic curve is flat above its top
        # block, which is exactly the behaviour we want: a plant with 44 refusals
        # is far outside anything the training set contained, and the honest
        # answer is "as high as we have ever been able to verify", not 99.9%.
        p = apply_isotonic(cal, z)
        raw = 1 / (1 + math.exp(-max(-30, min(30, z))))
        lo, hi = interval(cal, z)
        contrib = {n: ((f[n] - mu[i]) / sd[i]) * w[i + 1]
                   for i, n in enumerate(MODEL_NAMES)}
        seen = bool(hist.insp.get(fei_key)) or bool(hist.refu.get(fei_key))
        return {
            "fei": fei_key,
            # "UNKNOWN" is a placeholder, not a name. FDA's own OASIS rows carry
            # no firm for some establishments (63 refusal rows for 3001027464,
            # every one of them blank), so say that plainly instead of putting the
            # word UNKNOWN at the top of the board.
            "label": (label if (label or "").strip().upper() != "UNKNOWN" else "")
                     or reg.get(fei_key, {}).get("firm")
                     or ("unnamed establishment, FEI " + fei_key
                         + (f" ({country})" if country else "")),
            "country": country or None,
            "p12": round(p, 4), "band": band(p),
            # What the uncalibrated logit said. Shipped so the correction is
            # visible rather than silent — for the worst plants raw is ~0.999.
            "p12_uncalibrated": round(raw, 4),
            # 95% interval from the calibration block this plant landed in. A
            # bare "46%" implies precision that 50 plants cannot support.
            "p12_range": [round(lo, 4), round(hi, 4)],
            # True when the plant is above everything the data can distinguish.
            # It means "at least this", not "exactly this" — rank inside the
            # group with `p12_uncalibrated`.
            "at_ceiling": p >= max(b["p"] for b in cal) - 1e-9,
            # A plant with no FDA record scores the base rate. That is not a
            # prediction about the plant, it is "we know nothing" wearing a
            # percentage, and the UI must be able to tell the two apart.
            "basis": "history" if seen else "base_rate_only",
            "evidence": _plain(f, hist, fei_key, today, contrib),
            "drivers": {n: round(c, 3) for n, c in
                        sorted(contrib.items(), key=lambda t: -abs(t[1]))[:3]},
            "features": {n: round(f[n], 4) for n in MODEL_NAMES},
        }

    for node_id, plants_for_node in sorted(nodes_to_plants.items()):
        recs = [score_one(pl["fei"], pl["label"], pl.get("country") or "")
                for pl in plants_for_node]
        # Worst site wins: a buyer is exposed to the weakest plant, not the mean.
        # Tie-break on the uncalibrated score — many plants now sit at the
        # calibration ceiling, and "first in the list" is not an ordering.
        worst = max(recs, key=lambda r: (r["p12"], r["p12_uncalibrated"]))
        scored[node_id] = {**worst, "node_id": node_id,
                           "sites": len(recs),
                           "site_feis": [r["fei"] for r in recs]}
        if worst["basis"] == "base_rate_only":
            no_history += 1
        # Every underlying facility is addressable on its own too.
        for r in recs:
            scored.setdefault(f"facility:fei:{r['fei']}",
                              {**r, "node_id": f"facility:fei:{r['fei']}",
                               "sites": 1, "site_feis": [r["fei"]]})

    ui = ui_nodes()
    direct = len([i for i in ui if i in scored])
    added = propagate(scored, ui)
    covered = len([i for i in ui if i in scored])
    print(f"  UI graph: {len(ui)} nodes — {direct} scored directly, "
          f"{added} inherited from the plant behind them, "
          f"{covered} covered ({covered/len(ui)*100:.1f}%)")

    doc = {
        "run_at": today.isoformat(),
        "rule": "next-failure-v1",
        "rule_text": ("Logistic model on nine features of a plant's FDA inspection and "
                      "import-refusal history at a cutoff, trained on every actively "
                      "inspected drug establishment; predicts a failed inspection or a "
                      "manufacturing import refusal in the following 12 months. For a "
                      "node that is not a place (a product, API, drug or precursor) the "
                      "figure is that of the most at-risk plant behind it; "
                      "`upstream_plants` says how many others there are."),
        "horizon_days": 365,
        "trained_at": TRAIN_CUTOFF.isoformat(),
        "bands": {"low": "<2%", "raised": "2–6%", "high": ">6%"},
        "coverage": {"ui_nodes": len(ui), "scored": covered,
                     "direct": direct, "inherited": added},
        "basis_note": ("`basis: inherited` means the node is not a place and has "
                       "no record of its own — a product, API or drug — so it "
                       "carries the risk of the worst plant that makes it, named "
                       "in `inherited_from`. `basis: base_rate_only` means the "
                       "inspection or refusal record, so p12 is the population "
                       "average rather than anything about that plant. Show it "
                       "differently."),
        "calibration": {
            "method": "isotonic (pool-adjacent-violators) on 5-fold out-of-fold scores",
            "why": ("The raw logistic score ranks well and is over-confident at the "
                    "top: out of fold it reached 99.99% for a group whose observed "
                    "event rate was 36%. Isotonic regression cannot reorder plants, "
                    "so the ranking is untouched; it only makes the number match "
                    "the frequency actually observed at that score."),
            "ceiling": round(max(b["p"] for b in cal), 4),
            "ceiling_note": ("No plant can be shown above the ceiling, because "
                             "nothing in the data supports a higher number. The "
                             "ranking still separates plants at the ceiling — use "
                             "`p12_uncalibrated` for ordering within it."),
            "curve": [{"logit_at": round(b["at"], 4),
                       "observed_rate": round(b["p"], 5), "n": b["n"],
                       "range": [round(x, 4) for x in
                                 wilson(round(b["p"] * b["n"]), b["n"])]} for b in cal],
        },
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

    # Direct scores only. Inherited nodes carry their parent's `fei`, so a
    # fei-keyed dict lets a product overwrite the plant it inherited FROM and the
    # table then prints the plant's own row with the product's evidence line.
    ranked = sorted({v["fei"]: v for v in scored.values()
                     if v.get("basis") != "inherited"}.values(),
                    key=lambda r: (-r["p12"], -r["p12_uncalibrated"]))
    print(f"  {no_history} node(s) scored on the base rate only (no FDA record)")
    print(f"\n  {'plant':<44}{'p12':>7}  band     why")
    for r in ranked[:10]:
        print(f"  {(r['label'] or '')[:42]:<44}{r['p12']*100:>6.1f}%  {r['band']:<8} {r['evidence'][0][:52]}")
    print(f"\n  wrote {out.relative_to(REPO)} — {len(scored)} keys, "
          f"{len({v['fei'] for v in scored.values()})} distinct plants")
    return 0


if __name__ == "__main__":
    sys.exit(main())
