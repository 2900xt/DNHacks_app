"""Step 8 — news enrichment. Annotates the score; never silently overwrites it.

    python3 -m ml.risk.news            # top 8 plants by model score
    python3 -m ml.risk.news --all      # every scored plant (more API calls)

The model can only see what the FDA has written down, and its own
`not_modelled` list says so: export bans, fires, floods, a firm quietly leaving
the US market. Those show up in the news months before they show up in a federal
record — the 2022 Shanghai contrast-dye shutdown never entered openFDA's shortage
list at all.

So this searches for what the records cannot contain, using Claude with the
web-search tool, and attaches what it finds to the plant.

--------------------------------------------------------------------------------
Why the number does NOT move
--------------------------------------------------------------------------------

`p12` stays exactly what the logistic model produced. News findings are recorded
alongside it with their sources, plus a `suggested_adjustment` that is **never
applied automatically**.

That is a deliberate constraint, not timidity:

  * The model is *calibrated* — the top bucket predicts 5.0-5.6% and observes
    5.4-6.1%. A language model nudging that number destroys the property that
    makes a percentage meaningful, and nothing would tell you it had.
  * It is *reproducible*. Same inputs, same output, forever. A search result
    changes hourly.
  * `decisions/0003-transparent-risk-rules.md` requires a visible rule. "The
    model said 6.6% and then an LLM read the news and made it 9%" is not one.

A human raising a number because a plant caught fire is a good decision. The
system doing it silently is not. So: evidence up front, adjustment proposed,
never auto-applied.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RISK = REPO / "web" / "data" / "risk.json"
MODEL = "claude-opus-5"

PROMPT = """Search recent news for supply-chain disruption at this pharmaceutical \
manufacturing site.

  Company: {label}
  Country: {country}
  FDA facility identifier (FEI): {fei}

Look for events in roughly the last 18 months that would interrupt supply and that
would NOT appear in an FDA inspection or import-refusal record:

  - fire, flood, explosion, or other physical damage to a plant
  - a plant closure, suspension, or sale
  - an export ban, sanction, or trade action affecting the site or its country
  - a recall, or a regulatory action by a non-US regulator (EMA, WHO, MHRA)
  - the company exiting a product line or the US market
  - financial distress: bankruptcy, insolvency, default

Be strict about identity. Pharmaceutical company names collide constantly —
"United Laboratories" is several unrelated firms, and a parent's news is not
its subsidiary's. If you cannot confirm an article is about THIS company at THIS
site, do not report it.

Return ONLY a JSON object, no prose around it:

{{
  "findings": [
    {{"date": "YYYY-MM", "what": "one sentence", "url": "...",
      "severity": "high|medium|low", "confidence": "high|medium|low"}}
  ],
  "suggested_adjustment": 0.0,
  "rationale": "one sentence, or 'nothing found' "
}}

`suggested_adjustment` is a percentage-point change a human might consider
(e.g. 2.0 to add two points). Use 0.0 when nothing credible is found. Finding
nothing is the expected outcome for most plants and is a valid answer — do not
manufacture a finding to seem useful."""


def enrich(plants: list[dict], verbose: bool = True) -> dict[str, dict]:
    import anthropic
    client = anthropic.Anthropic()
    out: dict[str, dict] = {}

    for p in plants:
        try:
            resp = client.beta.messages.create(
                model=MODEL,
                max_tokens=4000,
                thinking={"type": "adaptive"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                tools=[{"type": "web_search_20260209", "name": "web_search",
                        "max_uses": 4}],
                messages=[{"role": "user", "content": PROMPT.format(
                    label=p["label"], country=p.get("country") or "unknown",
                    fei=p["fei"])}],
            )
            if getattr(resp, "stop_reason", None) == "refusal":
                out[p["fei"]] = {"error": "refused", "findings": []}
                continue
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            searches = sum(1 for b in resp.content
                           if getattr(b, "type", "") == "web_search_tool_result")
            start, end = text.find("{"), text.rfind("}")
            # An empty findings list and a failed parse are NOT the same thing, and
            # a bare `except: return []` makes them look identical - "we checked and
            # it is clean" versus "we never got an answer". Record which happened.
            if start < 0 or end <= start:
                data = {"findings": [], "parse_failed": True,
                        "raw": text[:400], "searches": searches}
            else:
                try:
                    data = json.loads(text[start:end + 1])
                    data["parse_failed"] = False
                except json.JSONDecodeError:
                    data = {"findings": [], "parse_failed": True,
                            "raw": text[:400], "searches": searches}
            data["searches"] = searches
        except Exception as e:                                   # noqa: BLE001
            out[p["fei"]] = {"error": f"{type(e).__name__}: {e}"[:160], "findings": []}
            if verbose:
                print(f"  ! {p['label'][:40]}: {type(e).__name__}")
            continue

        out[p["fei"]] = data
        if verbose:
            n = len(data.get("findings") or [])
            adj = data.get("suggested_adjustment") or 0.0
            flag = " ⚠️ NO JSON RETURNED" if data.get("parse_failed") else ""
            print(f"  {p['label'][:44]:<46} {data.get('searches', 0)} search(es), "
                  f"{n} finding(s)"
                  + (f", suggests {adj:+.1f}pp" if adj else "") + flag)
            for f in (data.get("findings") or [])[:2]:
                print(f"      {f.get('date','?')} · {f.get('severity','?'):6} · "
                      f"{(f.get('what') or '')[:76]}")
    return out


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY not set — news enrichment needs it")
    doc = json.loads(RISK.read_text())
    uniq = {v["fei"]: v for v in doc["plants"].values()}
    ranked = sorted(uniq.values(), key=lambda r: -r["p12"])
    n = len(ranked) if "--all" in sys.argv else 8
    print(f"NEWS ENRICHMENT — top {n} of {len(ranked)} plants by model score\n")

    found = enrich(ranked[:n])

    hits = 0
    for key, rec in doc["plants"].items():
        r = found.get(rec["fei"])
        if not r:
            continue
        rec["news"] = {
            "checked": True,
            "findings": r.get("findings") or [],
            "suggested_adjustment": r.get("suggested_adjustment") or 0.0,
            "rationale": r.get("rationale") or "",
            # Stated on the record so nobody can later assume it was applied.
            "applied": False,
            "searches": r.get("searches", 0),
            "parse_failed": bool(r.get("parse_failed")),
            "note": "p12 is the model's number. News is evidence for a human, "
                    "not an input to the score.",
        }
        if r.get("findings"):
            hits += 1
    doc["news_checked_at"] = __import__("datetime").date.today().isoformat()
    RISK.write_text(json.dumps(doc, indent=2) + "\n")
    failed = sum(1 for r in found.values() if r.get("parse_failed"))
    print(f"\n  {hits} plant(s) with findings · {failed} parse failure(s) · "
          f"p12 unchanged for all of them")
    print(f"  wrote {RISK.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
