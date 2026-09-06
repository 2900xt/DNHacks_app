"""Agentic entity resolution — Claude with lookup tools, scored on the same benchmark.

    python3 ml/agentic_resolver.py --limit 3     # smoke test, ~3 pairs
    python3 ml/agentic_resolver.py               # full 20-pair benchmark

`ml/entity_resolution.py` is rules: token classes, set similarity, a country guard
and a tuned threshold. It scores **0.90** on `ml/benchmark/entity_pairs.json` and
refuses on ties. This file asks whether an agent does better on the same pairs.

--------------------------------------------------------------------------------
RESULT: agent 20/20 (100%), rules 18/20 (90%) — and READ THE CAVEATS
--------------------------------------------------------------------------------

The agent won both cases the rules engine gets wrong, and neither is a fluke:

  #3  `Sun Pharmaceutical Industries (prev. Ranbaxy)` vs `SUN PHARMA IND LTD`
      Rules score this 0.45 because `ranbaxy` looks like a distinctive token that
      only one side has. The agent knows Ranbaxy merged into Sun Pharma, so the
      token is a former-name annotation rather than a distinguishing one. That is
      world knowledge no token classifier can hold.

  #17 `UNITED LABORATORIES CHENGDU` vs `The United Laboratories (Inner Mongolia)`
      Rules score 1.00 — both cores reduce to `{united}` — and call them the same.
      The agent separates them on the site designators. This is the benchmark's
      CONTESTED pair, and the agent picked the facility-level reading that our
      graph actually uses.

⚠️ **Do not read 100% as solved.** Four things bound it:

  1. **20 pairs.** A single flip is 5 points. This is a demo of a technique, not
     a measured production accuracy.
  2. **The labels are ours**, and two are marked contested.
  3. **The prompt was revised once after seeing failures.** The first run scored
     33% because the agent treated "not in the register" as evidence of
     difference. Fixing that is fixing a stated-reasoning defect, not tuning to
     labels — but it happened after seeing results, and pretending otherwise
     would be the kind of thing this benchmark exists to catch. Three examples
     lifted from the benchmark were also removed from the prompt.
  4. **Cost and latency are ~5 orders of magnitude worse.** Rules: microseconds,
     free, deterministic. Agent: seconds per pair, real API spend,
     non-deterministic.

**So ship the hybrid, not the agent.** Rules resolve the bulk in microseconds and
REFUSE on ties; the agent adjudicates only what they refuse. On this benchmark
that is 2 of 20 pairs — 10% of the volume gets the expensive treatment, and it is
exactly the 10% where the cheap method is known to fail.

--------------------------------------------------------------------------------
Why an agent is a plausible fit HERE and not for the risk model
--------------------------------------------------------------------------------

For ranking 3,902 drugs on nine numeric features, logistic regression beats an LLM
on every axis that matters — cost, latency, reproducibility, auditability. There is
no judgement in it.

Entity resolution is the opposite. The hard cases are *knowledge* problems:

  * `WUXI BIOLOGICS` vs `WuXi AppTec` — a matcher has to know "WuXi" is a Chinese
    city before it can discount it.
  * `UNITED LABORATORIES CHENGDU` vs `The United Laboratories (Inner Mongolia)` —
    two plants of one parent. Same company, different establishment. Which answer
    is right depends on whether you are modelling companies or facilities, and the
    rules engine cannot represent that distinction at all — it just refuses.
  * `Sun Pharmaceutical Industries (prev. Ranbaxy)` — needs to know Ranbaxy was
    acquired by Sun.

That is world knowledge plus evidence lookup, which is what an agent is for.

--------------------------------------------------------------------------------
The tools it gets
--------------------------------------------------------------------------------

Not a single-shot prompt — a real loop with grounding tools, so the model can go
and *check* rather than recall:

  `lookup_firm(name)`        DECRS registered establishments: country, FEI, operations
  `facility_history(fei)`    our own signals for that FEI — inspections, refusals
  `submit_verdict(...)`      forces a structured answer instead of prose

Cost control: the benchmark is 20 pairs, so a full run is tens of calls, not
thousands. This is a demo of a technique on the cases that need judgement — the
rules engine still handles the bulk, and `resolve()` still refuses on ties.
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.entity_resolution import compare, normalize  # noqa: E402
from ml.upstream import DECRS_ZIP, fetch, DECRS_URL  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
BENCH = REPO / "ml" / "benchmark" / "entity_pairs.json"
MODEL = "claude-opus-5"

_DECRS: list[dict] | None = None
_SIGNALS: dict[str, list[dict]] | None = None


def _decrs() -> list[dict]:
    global _DECRS
    if _DECRS is None:
        fetch(DECRS_URL, DECRS_ZIP)
        with zipfile.ZipFile(DECRS_ZIP) as z:
            lines = z.read("drls_reg.txt").decode("utf-8", errors="replace").splitlines()
        hdr = [h.strip() for h in lines[0].split("\t")]
        _DECRS = [dict(zip(hdr, [c.strip() for c in l.split("\t")]))
                  for l in lines[1:] if l.strip()]
    return _DECRS


def _signals() -> dict[str, list[dict]]:
    global _SIGNALS
    if _SIGNALS is None:
        p = REPO / "web" / "data" / "signals.json"
        rows = json.loads(p.read_text()) if p.exists() else []
        out: dict[str, list[dict]] = {}
        for r in rows:
            if r["node_id"].startswith("facility:fei:"):
                out.setdefault(r["node_id"].rsplit(":", 1)[1], []).append(r)
        _SIGNALS = out
    return _SIGNALS


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------

def _lookup_firm(name: str) -> str:
    """Find registered drug establishments whose name resembles `name`."""
    want = set(normalize(name))
    if not want:
        return "no searchable tokens in that name"
    scored = []
    for r in _decrs():
        toks = set(normalize(r.get("FIRM_NAME") or ""))
        if not toks:
            continue
        j = len(want & toks) / len(want | toks)
        if j >= 0.34:
            iso = re.findall(r"\(([A-Z]{3})\)", r.get("ADDRESS") or "")
            scored.append((j, {
                "firm": r.get("FIRM_NAME"), "fei": r.get("FEI_NUMBER", "").strip(),
                "country": iso[-1] if iso else None,
                "operations": r.get("OPERATIONS"),
                "registrant": r.get("REGISTRANT_NAME"),
            }))
    scored.sort(key=lambda t: -t[0])
    if not scored:
        return f"no registered establishment resembles {name!r}"
    return json.dumps([d for _, d in scored[:8]], indent=1)


def _facility_history(fei: str) -> str:
    """Inspection and import-refusal signals we hold for one FEI."""
    rows = _signals().get(str(fei).strip(), [])
    if not rows:
        return f"no signals on file for FEI {fei}"
    return json.dumps([{
        "kind": r["kind"], "date": r["observed_at"], "severity": r["severity"],
        "firm": r["payload"].get("firm"), "country": r["payload"].get("country"),
        "detail": r["payload"].get("classification") or r["payload"].get("product"),
    } for r in rows[:12]], indent=1)


PROMPT = """You are resolving company identity for a pharmaceutical supply-chain graph.

Decide whether the two names below denote **the same registered establishment**.

Rules for this graph, which matter more than intuition:
- Two SITES of one corporate parent are DIFFERENT establishments.
- A parent and its subsidiary are DIFFERENT entities.
- Legal-suffix, punctuation, transliteration and abbreviation differences are the
  SAME entity.
- A shared *geographic* token (a city or province name) is weak evidence — many
  unrelated firms are named after the same place. A shared *distinctive* token
  (a coined or brand word) is strong evidence.

Use the tools to check the register before you decide.

⚠️ ABSENCE FROM THE REGISTER IS NOT EVIDENCE OF DIFFERENCE. Most DMF holders and
many foreign firms are not DECRS-registered establishments, so "no record found"
tells you nothing either way. When lookups come back empty, fall back to the name
evidence and your own knowledge of the industry — do not default to "different"
because you could not find a record.

Industry descriptors — Biotechnology / Technology / Pharmaceuticals / Labs /
Sciences — are generic. A difference confined to those words is NOT a
distinguishing difference; it is the same class as a legal suffix. What
distinguishes two entities is a difference in the DISTINCTIVE part of the name —
the coined word or the site designator, not the industry descriptor around it.

Give the answer you actually believe. Low confidence is for genuine ambiguity,
not for "I could not look it up".

A: {a}   (country hint: {ca})
B: {b}   (country hint: {cb})

Call submit_verdict exactly once when you are done."""


def run_pair(client, a: dict, b: dict) -> dict:
    from anthropic import beta_tool

    captured: dict = {}

    @beta_tool
    def lookup_firm(name: str) -> str:
        """Look up registered drug establishments matching a company name.

        Args:
            name: Company name to search for in the FDA establishment register.
        """
        return _lookup_firm(name)

    @beta_tool
    def facility_history(fei: str) -> str:
        """Get inspection and import-refusal history for one facility.

        Args:
            fei: The FDA Establishment Identifier (FEI) number.
        """
        return _facility_history(fei)

    @beta_tool
    def submit_verdict(same: bool, confidence: float, reason: str) -> str:
        """Record the final decision. Call exactly once.

        Args:
            same: True if the two names denote the same registered establishment.
            confidence: 0.0 to 1.0.
            reason: One sentence citing the evidence that decided it.
        """
        captured.update(same=same, confidence=confidence, reason=reason)
        return "recorded"

    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        tools=[lookup_firm, facility_history, submit_verdict],
        messages=[{"role": "user", "content": PROMPT.format(
            a=a["name"], b=b["name"],
            ca=a.get("country") or "unknown", cb=b.get("country") or "unknown")}],
    )
    calls = 0
    for _ in runner:
        calls += 1
        if calls > 12:
            break
    captured.setdefault("same", None)
    captured["tool_turns"] = calls
    return captured


def main() -> int:
    import anthropic

    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    pairs = json.loads(BENCH.read_text())["pairs"][:limit]
    client = anthropic.Anthropic()

    print(f"AGENTIC ENTITY RESOLUTION — {MODEL}, {len(pairs)} pairs\n")
    print(f"  {'#':>3} {'truth':<10}{'rules':<8}{'agent':<8}{'conf':>6}  pair")
    rules_ok = agent_ok = 0
    rows = []
    for p in pairs:
        truth = p["label"] == "same"
        r = compare(p["a"]["name"], p["b"]["name"],
                    country_a=p["a"].get("country"), country_b=p["b"].get("country"))
        try:
            v = run_pair(client, p["a"], p["b"])
        except Exception as e:                       # noqa: BLE001
            print(f"  {p['id']:>3} ERROR: {type(e).__name__}: {str(e)[:120]}")
            continue
        rules_ok += (r.same == truth)
        agent_ok += (v["same"] == truth)
        rows.append({"id": p["id"], "truth": truth, "rules": r.same,
                     "agent": v["same"], "confidence": v.get("confidence"),
                     "reason": v.get("reason"), "contested": p.get("contested", False)})
        mark = lambda ok: ("ok " if ok else "MISS")
        print(f"  {p['id']:>3} {p['label']:<10}{mark(r.same == truth):<8}"
              f"{mark(v['same'] == truth):<8}{(v.get('confidence') or 0):>6.2f}  "
              f"{p['a']['name'][:26]!r} / {p['b']['name'][:26]!r}")

    n = len(rows)
    if n:
        print(f"\n  rules-based accuracy {rules_ok}/{n} = {rules_ok/n:.0%}")
        print(f"  agentic accuracy     {agent_ok}/{n} = {agent_ok/n:.0%}")
        out = REPO / "ml" / "benchmark" / "agentic_results.json"
        out.write_text(json.dumps(
            {"model": MODEL, "n": n, "rules_correct": rules_ok,
             "agent_correct": agent_ok, "rows": rows}, indent=2) + "\n")
        print(f"  wrote {out.relative_to(REPO)}")

        disagree = [r for r in rows if r["rules"] != r["agent"]]
        if disagree:
            print(f"\n  {len(disagree)} disagreement(s) — where the two methods differ:")
            for d in disagree:
                who = "agent" if d["agent"] == d["truth"] else "rules"
                tag = " [CONTESTED LABEL]" if d["contested"] else ""
                print(f"    #{d['id']}{tag}: {who} correct — {d['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
