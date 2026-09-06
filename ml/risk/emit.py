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

import collections
import json
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ml.risk.features import MODEL_NAMES, History, feature_table  # noqa: E402
from ml.risk.inspections import fei as norm_fei  # noqa: E402
from ml.risk.inspections import load as load_inspections  # noqa: E402
from ml.risk.labels import labeller  # noqa: E402
from ml.risk.refusals import load as load_refusals  # noqa: E402
from ml.risk.model import fit  # noqa: E402
from ml.risk.calibrate import (apply_isotonic, fit_isotonic, interval,  # noqa: E402
                               reliability, wilson)
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

#: Relations that are MOLECULE-LEVEL association, not supply. `drug:amoxicillin
#: -marketed_as-> product:ndc:0093-2267` says that NDC contains amoxicillin. It
#: does NOT say the 52 plants making amoxicillin worldwide make *that* pack.
#:
#: Propagating risk across them was wrong and loudly so: 504 of the 521 nodes
#: sitting at the calibration ceiling traced to ONE unnamed Guatemalan plant,
#: because every amoxicillin NDC inherited the worst of all 52. NDC 0093-2267 is
#: a Teva product and Teva is scored — the graph had the right answer one edge
#: away, via `company -markets-> product`.
#:
#: So a product takes its MARKETER's risk. Where the marketer is unresolved there
#: is no honest supply path, and the node is left to the molecule-level fallback
#: with `attribution: "molecule"` set so the weaker claim is visible.
MOLECULE_ONLY = {"marketed_as", "formulated_into"}


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
    edges, weak = [], []
    for f in sorted((REPO / "web" / "data").glob("edges.*.json")):
        for e in json.loads(f.read_text()):
            src, dst, rel = e.get("src"), e.get("dst"), e.get("rel", "")
            if not src or not dst:
                continue
            pair = (dst, src) if rel in REVERSED else (src, dst)
            (weak if rel in MOLECULE_ONLY else edges).append(pair)

    out = defaultdict(list)
    for a, b in edges:
        out[a].append(b)
    weak_out = defaultdict(list)
    for a, b in weak:
        weak_out[a].append(b)

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

    # Same again including the molecule-level edges. A node whose risk came down
    # the weak path has NOTHING upstream on the supply graph, so counting only
    # the strong one reported `upstream_plants: 0` for all 108 of them. For those
    # the honest count is "plants making the same substance", which is exactly
    # what the weak graph holds.
    behind_any = {k: set(v) for k, v in behind.items()}
    both = defaultdict(list)
    for k, v in out.items():
        both[k].extend(v)
    for k, v in weak_out.items():
        both[k].extend(v)
    for src, dsts in both.items():
        if src.startswith(("facility:", "company:")):
            for d in dsts:
                behind_any.setdefault(d, set()).add(src)
    for _ in range(len(nodes) + 1):
        grew = False
        for src, dsts in both.items():
            a = behind_any.get(src) or set()
            for d in dsts:
                t = behind_any.setdefault(d, set())
                if a - t:
                    t |= a
                    grew = True
        if not grew:
            break

    def n_plants(node: str) -> int:
        """Distinct FEIs upstream, not distinct producer NODES.

        A company node is one node and several plants. Counting nodes made every
        product read `upstream_plants: 1`, which looks like "single-sourced" — a
        strong claim — when it only meant "one marketer, who has six sites".
        """
        def feis_of(srcs) -> set:
            f = set()
            for src in srcs or ():
                rec = scored.get(src)
                if rec:
                    f.update(rec.get("site_feis") or [rec["fei"]])
            return f

        # Fall back on an empty FEI SET, not an empty source set. These nodes do
        # have a producer upstream — an unresolved marketer — so the source set is
        # non-empty while contributing no plants, and testing the source set left
        # all 108 reporting zero.
        return len(feis_of(behind.get(node)) or feis_of(behind_any.get(node)))

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
                               "attribution": "supply",
                               "inherited_from": origin,
                               "inherited_via": src,
                               "upstream_plants": n_plants(dst),
                               "evidence": [f"No FDA record of its own — this is "
                                            f"the risk of {base['label']}, which "
                                            f"makes it."] + why[:2]}
                n_up = n_plants(dst)
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

    # Second pass, molecule-level, for whatever the supply path could not reach —
    # a product whose marketer we could not resolve. Marked so it is never
    # mistaken for the real thing.
    for _ in range(len(nodes) + 1):
        changed = False
        for src in list(weak_out):
            base = scored.get(src)
            if not base:
                continue
            for dst in weak_out[src]:
                if dst not in nodes or dst in scored:
                    continue
                why = [e for e in base["evidence"]
                       if not e.startswith("No FDA record of its own")
                       and "sit upstream of this" not in e]
                scored[dst] = {**base, "node_id": dst, "basis": "inherited",
                               "attribution": "molecule",
                               "inherited_from": base.get("inherited_from") or src,
                               "inherited_via": src,
                               "upstream_plants": n_plants(dst),
                               "evidence": [f"No supplier we could resolve — this is "
                                            f"the risk of the most at-risk plant "
                                            f"making the same substance "
                                            f"({base['label']}), which may not be "
                                            f"the plant that makes this one."] + why[:2]}
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


def training_provenance(hist: History, feis, Y, cal) -> dict:
    """What the model was actually trained on, counted from the loaded rows.

    Every figure here is computed, never typed in. A provenance block that is
    hand-maintained is a provenance block that is wrong by the second commit, and
    the whole claim of this panel is that the number on screen is earned.
    """
    insp = load_inspections()
    refu = load_refusals()

    def span(ds):
        # Parse before sorting. The two feeds use different formats — DECRS gives
        # "12/31/2024", OASIS gives "31-Oct-25" — so sorting the raw strings put
        # the inspection range at 2011-2024 when it actually runs to 2026.
        got = sorted(d for d in (parse_date(x) for x in ds) if d)
        return {"from": got[0].isoformat(), "to": got[-1].isoformat()} if got else {}

    ic = collections.Counter(r["classification"] for r in insp)
    rc = collections.Counter(r["kind"] for r in refu)
    icountry = collections.Counter(r["country_code"] for r in insp if r["country_code"])

    return {
        "sources": [
            {"name": "FDA Inspection Classification Database",
             "what": "every drug-establishment inspection and how it ended",
             "rows": len(insp),
             "breakdown": {"NAI (no action)": ic.get("NAI", 0),
                           "VAI (voluntary action)": ic.get("VAI", 0),
                           "OAI (official action)": ic.get("OAI", 0)},
             "span": span(r["end_date"] for r in insp),
             "establishments": len({r["fei"] for r in insp if r["fei"]}),
             "countries": len(icountry),
             "url": "https://datadashboard.fda.gov/ora/cd/inspections.htm"},
            {"name": "FDA OASIS import refusals",
             "what": "shipments turned away at the US border",
             "rows": len(refu),
             "breakdown": {"manufacturing quality (charge 27, 3280)": rc.get("mfg", 0),
                           "paperwork (charge 118, 472)": rc.get("paperwork", 0)},
             "span": span(r["date"] for r in refu),
             "establishments": len({r["fei"] for r in refu if r["fei"]}),
             "url": "https://www.accessdata.fda.gov/scripts/importrefusals/"},
            {"name": "FDA DECRS drug establishment register",
             "what": "who is registered to manufacture, and where",
             "rows": len(decrs()),
             "url": "https://www.fda.gov/drugs/drug-approvals-and-databases/"
                    "drug-establishments-current-registration-site"},
        ],
        "fit": {
            "cutoff": TRAIN_CUTOFF.isoformat(),
            "plants": len(feis),
            "positives": int(sum(Y)),
            "base_rate": round(sum(Y) / len(Y), 5),
            "horizon_days": 365,
            "label": ("a failed inspection (OAI) or a manufacturing import refusal "
                      "in the 365 days after the cutoff"),
            "why_this_cutoff": ("The most recent date with a full year of outcomes "
                                "behind it. Anything later and the label is only "
                                "partly observed, which reads as a lower risk than "
                                "is real."),
            "features": len(MODEL_NAMES),
            "features_withheld": ["insp_3y", "months_since_insp"],
            "withheld_because": ("They measure FDA's inspection SCHEDULE, not plant "
                                 "risk. You cannot fail an inspection that never "
                                 "happens, so leaving them in lets the model predict "
                                 "the detector instead of the event."),
        },
        "calibration_blocks": len(cal),
        "out_of_fold": ("Every calibration figure comes from 5-fold cross-validation "
                        "— each plant scored by a model that never saw it."),
    }


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
        # Fall back to DECRS when the caller has no country. 77 plants reached
        # here with none, and an absent country is not neutral: it silently reads
        # as "not China, not India", which is the model asserting something it was
        # never told. DECRS knows all 77.
        country = (country or reg.get(fei_key, {}).get("country") or "").upper()
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
            # Predicted vs observed, out of fold. The evidence that the number on
            # screen is a percentage and not a ranking dressed as one.
            "reliability": reliability(cal, oof, [int(y) for y in Y]),
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
        "training": training_provenance(hist, feis, Y, cal),
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

    # A second, compact file for the browser.
    #
    # risk.json is the artifact of record: every feature, every driver, every
    # site, for anyone auditing the model. That makes it 2 MB, and the largest
    # thing the web bundle imports today is 702 KB — three times over is a real
    # cost in TypeScript inference and bundle tracing for fields no screen reads.
    #
    # So the console gets only what it draws. Same run, same numbers, no drift:
    # a hand-maintained second copy would be wrong by the second commit.
    ui_doc = {
        "_note": ("Compact projection of risk.json for the web bundle. Emitted by "
                  "the same run — do not hand-edit. risk.json is the artifact of "
                  "record; audit against that."),
        "run_at": doc["run_at"],
        "trained_at": doc["trained_at"],
        "horizon_days": doc["horizon_days"],
        "rule_text": doc["rule_text"],
        "coverage": doc["coverage"],
        "calibration": {k: doc["calibration"][k]
                        for k in ("method", "ceiling", "reliability", "curve")},
        "training": doc["training"],
        "not_modelled": doc["not_modelled"],
        "plants": {
            k: {kk: v[kk] for kk in
                ("p12", "p12_range", "band", "evidence", "basis", "attribution",
                 "label", "upstream_plants", "at_ceiling")
                # Identity, not `in (None, False)`: 0.0 == False in Python, and
                # that test silently dropped p12 from every plant scored at 0.
                if kk in v and v[kk] is not None and v[kk] is not False}
            for k, v in scored.items()
        },
    }
    ui_out = REPO / "web" / "data" / "risk.ui.json"
    ui_out.write_text(json.dumps(ui_doc, separators=(",", ":")) + "\n")

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
    print(f"  wrote {ui_out.relative_to(REPO)} — "
          f"{ui_out.stat().st_size / 1024:.0f} KB for the browser "
          f"(risk.json is {out.stat().st_size / 1024:.0f} KB)")
    return 0


def selftest() -> int:
    """Check the ARTIFACT, not the model. Every one of these caught a real bug.

    A model self-check cannot see any of this: the model was fine while a Teva
    product was reading a Guatemalan plant's risk, while 77 plants were being
    told they were not in China, and while 46 plants published a probability
    outside their own confidence interval.
    """
    doc = json.loads((REPO / "web" / "data" / "risk.json").read_text())
    P, cov = doc["plants"], doc["coverage"]
    fails = []

    def check(ok, msg):
        print(f"  [{'OK ' if ok else 'FAIL'}] {msg}")
        if not ok:
            fails.append(msg)

    bad_range = [k for k, v in P.items()
                 if not (v["p12_range"][0] <= v["p12"] <= v["p12_range"][1])]
    check(not bad_range, f"every p12 lies inside its own p12_range "
                         f"({len(bad_range)} violations)")

    ceil = doc["calibration"]["ceiling"]
    check(all(v["p12"] <= ceil + 1e-9 for v in P.values()),
          f"nothing is shown above the {ceil*100:.0f}% calibration ceiling")

    at = [v for v in P.values() if abs(v["p12"] - ceil) < 1e-9]
    check(len(at) / len(P) < 0.05,
          f"the ceiling is rare, not the default — {len(at)}/{len(P)} nodes "
          f"({len(at)/len(P)*100:.1f}%)")

    # One plant driving a large share of the board means risk is being propagated
    # across an edge that is association rather than supply. That is exactly how
    # 504 amoxicillin packs came to inherit one Guatemalan plant.
    inh = [v for v in P.values() if v["basis"] == "inherited"]
    if inh:
        top, n = collections.Counter(v["inherited_from"] for v in inh).most_common(1)[0]
        check(n / len(inh) < 0.25,
              f"no single plant dominates the inherited nodes — worst is {top} "
              f"at {n}/{len(inh)} ({n/len(inh)*100:.0f}%)")

    direct = [v for v in P.values() if v["basis"] != "inherited"]
    seen, uniq = set(), []
    for v in direct:
        if v["fei"] not in seen:
            seen.add(v["fei"])
            uniq.append(v)
    noc = [v for v in uniq if not v.get("country")]
    check(len(noc) / len(uniq) < 0.02,
          f"country is known for essentially every plant — {len(noc)}/{len(uniq)} "
          f"missing (absent reads as 'not China, not India')")

    zero_up = [k for k, v in P.items()
               if v["basis"] == "inherited" and not v.get("upstream_plants")]
    check(not zero_up, f"every inherited node counts at least one plant upstream "
                       f"({len(zero_up)} report zero)")

    check(all(v.get("evidence") for v in P.values()), "every node has evidence")
    check(all(v["basis"] != "inherited" or v.get("inherited_from")
              for v in P.values()), "every inherited node names its origin")
    check(cov["scored"] / cov["ui_nodes"] > 0.95,
          f"UI coverage {cov['scored']}/{cov['ui_nodes']} "
          f"({cov['scored']/cov['ui_nodes']*100:.1f}%)")

    print("\n  PASS" if not fails else f"\n  FAIL — {len(fails)} problem(s)")
    return 0 if not fails else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print("risk artifact self-check\n")
        sys.exit(selftest())
    sys.exit(main())
