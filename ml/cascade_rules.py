"""Risk rules for the CHOKEPOINT cascade — the thresholds and the evidence.

The graph traversal (BFS up the dependency edges) lives in `web/src/lib/graph.ts`.
This module owns *why* a node turns red, and what evidence we show for it.

Decision 0003: transparent rules, not a model. Every red node can name the rule
that fired it and the signals that satisfied that rule.

    python3 ml/cascade_rules.py --emit    # thresholds as JSON, for graph.ts
    python3 ml/cascade_rules.py           # self-check against the anchor signals

--------------------------------------------------------------------------------
The one non-obvious thing in here: events vs. states.
--------------------------------------------------------------------------------

The starting rule was "concentration > 75% in one country AND >= 1 live negative
signal in 90 days". Applied literally it cannot fire our best evidence:

    CSPC Zhongnuo  refusal  2026-07-24    43 days   fires
    Centrient      OAI      2026-01-27   221 days   does not
    Aurobindo      OAI      2025-09-05   365 days   does not

Aurobindo is the node the amoxicillin story rests on (FEI 3004446312 -> exact
openFDA labeler_name on 19 amoxicillin NDCs, no fuzzy matching). Widening the
window to catch it is the wrong fix, because the problem is not the number:

  * An import refusal is an EVENT. It happened on a date and it is over.
    "Was there one recently?" is the right question.
  * An OAI classification is a STATE. A facility *is* classified OAI and stays
    that way until FDA re-inspects and reclassifies it. Centrient has OAIs in
    2018, 2022 and 2026 - three readings of one ongoing condition, not three
    incidents. FDA also posts classifications months after the inspection ends,
    so a 90-day recency window can almost never catch one.

So events get a recency window; states get a "what is it now?" check. That keeps
the 90-day number honest instead of stretching it to 400 to make a demo work.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable, Literal

# --------------------------------------------------------------------------
# Thresholds. Shaurya: these are the numbers; `--emit` gives them to you as JSON.
# --------------------------------------------------------------------------

#: A node is concentrated if one country holds more than this share of supply.
CONCENTRATION_THRESHOLD = 0.75

#: Recency window for *event* signals, in days.
EVENT_WINDOW_DAYS = 90

#: Classifications that count as a hard negative on a facility.
#: NAI = No Action Indicated, VAI = Voluntary Action Indicated, OAI = Official Action.
NEGATIVE_CLASSIFICATIONS = frozenset({"OAI"})

Semantics = Literal["event", "state"]

#: How each signal kind behaves. This is the table that fixes the 90-day problem.
SIGNAL_SEMANTICS: dict[str, Semantics] = {
    "import_refusal": "event",           # OASIS - happened on a date
    "regulatory_action": "event",        # Federal Register - published on a date
    "news_event": "event",               # GDELT - reported on a date
    "recall": "event",                   # openFDA enforcement
    "shortage": "state",                 # openFDA - a drug *is* in shortage
    "inspection_classification": "state",  # FDA - a facility *is* NAI/VAI/OAI
}


@dataclass(frozen=True)
class Signal:
    """One row of `web/data/signals.json`."""

    node_id: str
    kind: str
    severity: str
    source: str
    observed_at: date
    url: str | None = None
    payload: dict = field(default_factory=dict)

    @property
    def semantics(self) -> Semantics:
        return SIGNAL_SEMANTICS.get(self.kind, "event")

    @classmethod
    def from_json(cls, row: dict) -> "Signal":
        return cls(
            node_id=row["node_id"],
            kind=row["kind"],
            severity=row.get("severity", "unknown"),
            source=row.get("source", "unknown"),
            observed_at=_parse_date(row["observed_at"]),
            url=row.get("url"),
            payload=row.get("payload", {}) or {},
        )


def _parse_date(value) -> date:
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


# --------------------------------------------------------------------------
# The two halves of the rule
# --------------------------------------------------------------------------


def firing_events(signals: Iterable[Signal], *, as_of: date) -> list[Signal]:
    """Event signals inside the recency window."""
    cutoff = as_of - timedelta(days=EVENT_WINDOW_DAYS)
    return sorted(
        (s for s in signals if s.semantics == "event" and cutoff <= s.observed_at <= as_of),
        key=lambda s: s.observed_at,
        reverse=True,
    )


def firing_states(signals: Iterable[Signal]) -> list[Signal]:
    """Adverse states that are *current*.

    "Current" means the most recent reading of that state, per node, is adverse.
    An older OAI that has since been re-inspected as NAI must NOT fire - that is
    what makes this a status check rather than a wider window.
    """
    latest: dict[tuple[str, str], Signal] = {}
    for s in signals:
        if s.semantics != "state":
            continue
        key = (s.node_id, s.kind)
        if key not in latest or s.observed_at > latest[key].observed_at:
            latest[key] = s
    return sorted(
        (s for s in latest.values() if _is_adverse_state(s)),
        key=lambda s: s.observed_at,
        reverse=True,
    )


def _is_adverse_state(s: Signal) -> bool:
    if s.kind == "inspection_classification":
        return str(s.payload.get("classification", "")).upper() in NEGATIVE_CLASSIFICATIONS
    if s.kind == "shortage":
        return str(s.payload.get("status", "")).lower() in {"current", "to be discontinued"}
    return s.severity in {"high", "critical"}


# --------------------------------------------------------------------------
# The verdict
# --------------------------------------------------------------------------

RULE_ID = "concentrated-and-negative-v1"
RULE_TEXT = (
    f"Red if one country holds >{CONCENTRATION_THRESHOLD:.0%} of supply "
    f"AND (a negative event in the last {EVENT_WINDOW_DAYS} days "
    f"OR the facility is currently {'/'.join(sorted(NEGATIVE_CLASSIFICATIONS))})."
)


@dataclass
class Verdict:
    node_id: str
    red: bool
    rule: str
    rule_text: str
    reasons: list[str]
    fired_by: list[dict]

    def to_json(self) -> dict:
        return {
            "node_id": self.node_id,
            "red": self.red,
            "rule": self.rule,
            "rule_text": self.rule_text,
            "reasons": self.reasons,
            "firedBy": self.fired_by,
        }


def evaluate(
    node_id: str,
    signals: Iterable[Signal],
    *,
    concentration: float | None = None,
    as_of: date | None = None,
) -> Verdict:
    """Decide whether one node is red, and show the work.

    `concentration` is the single-country share of supply for this node (0-1),
    or None when we have not computed one - in which case the concentration half
    of the rule is treated as unproven rather than as satisfied.
    """
    as_of = as_of or date.today()
    signals = list(signals)

    events = firing_events(signals, as_of=as_of)
    states = firing_states(signals)

    concentrated = concentration is not None and concentration > CONCENTRATION_THRESHOLD
    has_negative = bool(events or states)

    reasons: list[str] = []
    if concentration is None:
        reasons.append("concentration unknown - not counted toward the rule")
    elif concentrated:
        reasons.append(f"{concentration:.0%} of supply in one country (> {CONCENTRATION_THRESHOLD:.0%})")
    else:
        reasons.append(f"{concentration:.0%} single-country share is under the {CONCENTRATION_THRESHOLD:.0%} threshold")

    for s in events:
        age = (as_of - s.observed_at).days
        reasons.append(f"{s.kind} {age}d ago ({s.observed_at}, {s.source}) - within {EVENT_WINDOW_DAYS}d")
    for s in states:
        detail = s.payload.get("classification") or s.payload.get("status") or s.severity
        reasons.append(f"currently {detail} ({s.kind}, last read {s.observed_at}, {s.source})")

    return Verdict(
        node_id=node_id,
        red=concentrated and has_negative,
        rule=RULE_ID,
        rule_text=RULE_TEXT,
        reasons=reasons,
        fired_by=[
            {
                "kind": s.kind,
                "semantics": s.semantics,
                "observed_at": s.observed_at.isoformat(),
                "source": s.source,
                "url": s.url,
                "severity": s.severity,
            }
            for s in (*events, *states)
        ],
    )


# --------------------------------------------------------------------------
# Handoff + self-check
# --------------------------------------------------------------------------


def thresholds() -> dict:
    """The numbers, for `web/src/lib/graph.ts`. Keep this the single source."""
    return {
        "rule": RULE_ID,
        "rule_text": RULE_TEXT,
        "concentration_threshold": CONCENTRATION_THRESHOLD,
        "event_window_days": EVENT_WINDOW_DAYS,
        "negative_classifications": sorted(NEGATIVE_CLASSIFICATIONS),
        "signal_semantics": SIGNAL_SEMANTICS,
    }


#: The three signals the demo fires on. Dates are real and must not be edited -
#: they are public FDA records and a judge can look them up.
ANCHORS = [
    Signal(
        node_id="facility:fei:3004446312",
        kind="inspection_classification",
        severity="high",
        source="FDA Inspection Classification",
        observed_at=date(2025, 9, 5),
        payload={"classification": "OAI", "firm": "Aurobindo Pharma Limited", "country": "IN"},
    ),
    Signal(
        node_id="facility:fei:3004497364",
        kind="inspection_classification",
        severity="high",
        source="FDA Inspection Classification",
        observed_at=date(2026, 1, 27),
        payload={"classification": "OAI", "firm": "Centrient Pharmaceuticals India", "country": "IN"},
    ),
    Signal(
        node_id="facility:fei:3003196232",
        kind="import_refusal",
        severity="high",
        source="OASIS import refusals",
        observed_at=date(2026, 7, 24),
        payload={"product": "AMOXICILLIN TRIHYDRATE", "firm": "CSPC Zhongnuo", "country": "CN"},
    ),
]


def _self_check(as_of: date) -> int:
    print(f"rule: {RULE_TEXT}\nas of: {as_of}\n")
    failures = 0
    for anchor in ANCHORS:
        v = evaluate(anchor.node_id, [anchor], concentration=0.94, as_of=as_of)
        age = (as_of - anchor.observed_at).days
        mark = "OK  " if v.red else "FAIL"
        if not v.red:
            failures += 1
        firm = anchor.payload.get("firm", anchor.node_id)
        print(f"[{mark}] {firm:34s} {anchor.kind:26s} {age:>4}d  red={v.red}")
        for r in v.reasons[1:]:
            print(f"       - {r}")

    # A facility re-inspected clean must stop firing, or this is just a wide window.
    cleared = [
        ANCHORS[0],
        Signal(
            node_id=ANCHORS[0].node_id,
            kind="inspection_classification",
            severity="low",
            source="FDA Inspection Classification",
            observed_at=date(2026, 6, 1),
            payload={"classification": "NAI", "firm": "Aurobindo Pharma Limited"},
        ),
    ]
    v = evaluate(ANCHORS[0].node_id, cleared, concentration=0.94, as_of=as_of)
    if v.red:
        failures += 1
        print("\n[FAIL] re-inspected NAI still fires - the state check is not working")
    else:
        print("\n[OK  ] a later NAI clears the earlier OAI (state, not a wider window)")

    print(f"\n{'all anchors fire' if failures == 0 else f'{failures} failure(s)'}")
    return failures


if __name__ == "__main__":
    if "--emit" in sys.argv:
        print(json.dumps(thresholds(), indent=2))
    else:
        sys.exit(_self_check(date(2026, 9, 5)))
