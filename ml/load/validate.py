#!/usr/bin/env python3
"""Validate web/data/*.json against the data contract.

There is no database (decision 0004) — these JSON artifacts *are* the schema, so
this script is the only thing standing between a typo and a silently broken graph.

Contract: DNHacks_brain/team/briefs/README.md - "The data contract"

    nodes.*.json       [{ id, type, label, country, critical, attrs, resolved_by }]
    edges.*.json       [{ src, dst, rel, layer, citation }]
    compliance.json    [{ node_id, taa_pass, on_1260h, evidence }]
    signals.json       [{ node_id, kind, severity, source, observed_at, url, payload }]
    bins.json          [{ id, label, covers_drugs, country }]
    backtest.json      { run_at, cutoff, params, result }

Usage:
    python ml/load/validate.py                 # validate every file present
    python ml/load/validate.py --data-dir DIR  # non-default location

Exits 1 if any file violates the contract, 0 otherwise. Warnings never fail the
run: lanes land asynchronously, so an edge pointing at a node another producer
has not written yet is expected, not an error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = REPO_ROOT / "web" / "data"

# --- the node-id scheme -----------------------------------------------------
# type:key, lowercase, ASCII, hyphen-separated. FEI wins; company:name: is the
# last resort and must be flagged fuzzy so the UI can mark it.
NODE_ID_PATTERNS = [
    (re.compile(r"^drug:[a-z0-9-]+$"), "drug"),
    (re.compile(r"^product:ndc:[a-z0-9-]+$"), "product"),
    (re.compile(r"^api:[a-z0-9-]+$"), "api"),
    (re.compile(r"^precursor:[a-z0-9-]+$"), "precursor"),
    (re.compile(r"^company:fei:\d+$"), "company"),
    (re.compile(r"^company:duns:\d+$"), "company"),
    (re.compile(r"^company:name:[a-z0-9-]+$"), "company"),
    (re.compile(r"^country:[a-z]{2}$"), "country"),
    (re.compile(r"^facility:fei:\d+$"), "facility"),
]

# Required vs optional mirrors the app's TypeScript interfaces: a field declared
# `country?: string` is `string | undefined` under strict mode, so the artifacts
# OMIT it rather than writing null. Absent is correct; null would not type-check.
NODE_KEYS = {"id", "type", "label", "country", "critical", "attrs", "resolved_by"}
NODE_REQUIRED = {"id", "type"}
EDGE_KEYS = {"src", "dst", "rel", "layer", "citation"}
EDGE_REQUIRED = {"src", "dst", "rel", "layer"}
COMPLIANCE_KEYS = {"node_id", "taa_pass", "on_1260h", "evidence"}
COMPLIANCE_REQUIRED = {"node_id", "evidence"}
SIGNAL_KEYS = {"node_id", "kind", "severity", "source", "observed_at", "url", "payload"}
SIGNAL_REQUIRED = {"node_id", "kind", "observed_at"}
BIN_KEYS = {"id", "label", "covers_drugs", "country"}
BIN_REQUIRED = {"id", "covers_drugs"}

RESOLVED_BY = {"fei", "duns", "fuzzy"}
VALID_LAYERS = {1, 2, 3}

# Not a closed vocabulary — unknown rels warn rather than fail, so a lane can
# introduce one without breaking everyone else's build. `active_in`,
# `instance_of` and `markets` were added Sat 20:50 after reconciling against
# nikhil/openfda-graph; without them his 1,526 legitimate edges warn and drown
# the real findings.
#
# Sun 00:05: reconciled again against what the artifacts actually contain.
# `formulated_from` -> `formulated_into` and `instance_of` -> `marketed_as`
# (Nikhil's rename), and `operated_by` / `hosts` arrived with Parth's signal
# lane. All four were in the data and none were in this set, which is why the
# validator was emitting 1,532 warnings — every one of them vocabulary drift
# rather than a data fault. `labeled_by` is kept though currently unused.
KNOWN_RELS = {
    "feeds",            # precursor -> api          (Yash, layer 3)
    "produced_by",      # precursor/api/drug -> company/facility
    "formulated_into",  # api -> product            (Nikhil)
    "marketed_as",      # drug -> product           (Nikhil)
    "markets",          # company -> product        (Nikhil)
    "incorporated_in",  # company -> country
    "active_in",        # company -> country        (Nikhil)
    "labeled_by",       # product -> company
    "operated_by",      # facility -> company       (Parth, layer 2 via ER)
    "hosts",            # country/company -> facility
}

# Evidence has to carry a source. A PASS/FAIL with no citation is exactly what
# decision 0003 rules out.
CITATION_KEYS = {"far", "fr_doc", "url", "source", "citation", "dmf", "file", "cfr"}


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"{where}: {msg}")


def node_type_for(node_id: str) -> str | None:
    for pattern, node_type in NODE_ID_PATTERNS:
        if pattern.match(node_id):
            return node_type
    return None


def check_keys(rec: dict, known: set[str], required: set[str],
               where: str, rep: Report) -> None:
    missing = required - rec.keys()
    if missing:
        rep.error(where, f"missing required key(s): {', '.join(sorted(missing))}")
    nulls = {k for k in rec if rec[k] is None}
    if nulls:
        rep.error(where, f"key(s) set to null — omit them instead, the app's types "
                         f"declare optionals as `?: T` (undefined, not null): "
                         f"{', '.join(sorted(nulls))}")
    extra = rec.keys() - known
    if extra:
        rep.warn(where, f"key(s) not in the contract: {', '.join(sorted(extra))}")


def load_array(path: Path, rep: Report) -> list | None:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        rep.error(path.name, f"is not valid JSON — {exc}")
        return None
    if not isinstance(data, list):
        rep.error(path.name, f"must be a JSON array, got {type(data).__name__}")
        return None
    return data


def validate_nodes(path: Path, rep: Report) -> set[str]:
    """Returns the ids declared in this file, for cross-file reference checks."""
    rows = load_array(path, rep)
    if rows is None:
        return set()

    ids: set[str] = set()
    for i, rec in enumerate(rows):
        where = f"{path.name}[{i}]"
        if not isinstance(rec, dict):
            rep.error(where, "is not an object")
            continue
        check_keys(rec, NODE_KEYS, NODE_REQUIRED, where, rep)

        node_id = rec.get("id")
        if not isinstance(node_id, str) or not node_id:
            rep.error(where, "id must be a non-empty string")
            continue
        where = f"{path.name}[{i}] {node_id}"

        if node_id in ids:
            rep.error(where, "duplicate id within this file")
        ids.add(node_id)

        inferred = node_type_for(node_id)
        if inferred is None:
            rep.error(where, "id does not match the node-id scheme (type:key, lowercase ASCII)")
        elif rec.get("type") != inferred:
            rep.error(where, f"type is {rec.get('type')!r} but the id implies {inferred!r}")

        # FEI wins. company:name: is the last resort and MUST be flagged fuzzy.
        resolved_by = rec.get("resolved_by")
        if node_id.startswith("company:name:"):
            if resolved_by != "fuzzy":
                rep.error(
                    where,
                    f"company:name: ids must set resolved_by='fuzzy', got {resolved_by!r}",
                )
        elif node_id.startswith("company:fei:") and resolved_by not in (None, "fei"):
            rep.warn(where, f"id is FEI-based but resolved_by is {resolved_by!r}")
        elif node_id.startswith("company:duns:") and resolved_by not in (None, "duns"):
            rep.warn(where, f"id is DUNS-based but resolved_by is {resolved_by!r}")
        elif resolved_by is not None and resolved_by not in RESOLVED_BY:
            rep.error(where, f"resolved_by must be one of {sorted(RESOLVED_BY)} or null")

        country = rec.get("country")
        if country is not None and not (isinstance(country, str) and re.fullmatch(r"[a-z]{2}", country)):
            rep.error(where, f"country must be a lowercase ISO-2 string or null, got {country!r}")

        if not isinstance(rec.get("critical", False), bool):
            rep.error(where, "critical must be a boolean")
        if rec.get("attrs") is not None and not isinstance(rec["attrs"], dict):
            rep.error(where, "attrs must be an object or null")

    return ids


def validate_edges(path: Path, rep: Report) -> set[str]:
    """Returns the node ids this file references."""
    rows = load_array(path, rep)
    if rows is None:
        return set()

    referenced: set[str] = set()
    for i, rec in enumerate(rows):
        where = f"{path.name}[{i}]"
        if not isinstance(rec, dict):
            rep.error(where, "is not an object")
            continue
        check_keys(rec, EDGE_KEYS, EDGE_REQUIRED, where, rep)

        src, dst = rec.get("src"), rec.get("dst")
        rel = rec.get("rel")
        where = f"{path.name}[{i}] {src} --{rel}--> {dst}"

        for end, value in (("src", src), ("dst", dst)):
            if not isinstance(value, str) or not value:
                rep.error(where, f"{end} must be a non-empty string")
            elif node_type_for(value) is None:
                rep.error(where, f"{end} {value!r} does not match the node-id scheme")
            else:
                referenced.add(value)

        if rel and rel not in KNOWN_RELS:
            rep.warn(where, f"rel {rel!r} is outside the known vocabulary {sorted(KNOWN_RELS)}")

        layer = rec.get("layer")
        if layer not in VALID_LAYERS:
            rep.error(where, f"layer must be 1, 2 or 3 (got {layer!r})")

        # No citation, no edge. This is the credibility strategy, not decoration.
        citation = rec.get("citation")
        if layer == 3 and not (isinstance(citation, str) and citation.strip()):
            rep.error(where, "layer 3 requires a non-empty citation")

    return referenced


def validate_compliance(path: Path, rep: Report) -> set[str]:
    rows = load_array(path, rep)
    if rows is None:
        return set()

    referenced: set[str] = set()
    seen: set[str] = set()
    for i, rec in enumerate(rows):
        where = f"{path.name}[{i}]"
        if not isinstance(rec, dict):
            rep.error(where, "is not an object")
            continue
        check_keys(rec, COMPLIANCE_KEYS, COMPLIANCE_REQUIRED, where, rep)

        node_id = rec.get("node_id")
        where = f"{path.name}[{i}] {node_id}"
        if not isinstance(node_id, str) or node_type_for(node_id) is None:
            rep.error(where, "node_id must be a valid node id")
        else:
            if node_id in seen:
                rep.error(where, "duplicate node_id — compliance is one row per node")
            seen.add(node_id)
            referenced.add(node_id)

        for field in ("taa_pass", "on_1260h"):
            if not isinstance(rec.get(field), (bool, type(None))):
                rep.error(where, f"{field} must be true, false or null")

        # Every determination carries its citation (decision 0003).
        evidence = rec.get("evidence")
        if not isinstance(evidence, dict) or not evidence:
            rep.error(where, "evidence must be a non-empty object — every determination cites its source")
        elif not (evidence.keys() & CITATION_KEYS):
            rep.warn(where, f"evidence has no recognisable citation key {sorted(CITATION_KEYS)}")

    return referenced


def validate_bins(path: Path, rep: Report) -> set[str]:
    rows = load_array(path, rep)
    if rows is None:
        return set()

    referenced: set[str] = set()
    for i, rec in enumerate(rows):
        where = f"{path.name}[{i}]"
        if not isinstance(rec, dict):
            rep.error(where, "is not an object")
            continue
        check_keys(rec, BIN_KEYS, BIN_REQUIRED, where, rep)

        covers = rec.get("covers_drugs")
        if not isinstance(covers, list):
            rep.error(where, "covers_drugs must be an array")
            continue
        # covers_drugs holds drug: ids, not bare names — this is the hardware -> graph seam.
        for drug in covers:
            if not isinstance(drug, str) or not drug.startswith("drug:"):
                rep.error(where, f"covers_drugs must hold drug: ids, got {drug!r}")
            else:
                referenced.add(drug)

    return referenced


def validate_signals(path: Path, rep: Report) -> set[str]:
    rows = load_array(path, rep)
    if rows is None:
        return set()

    referenced: set[str] = set()
    for i, rec in enumerate(rows):
        where = f"{path.name}[{i}]"
        if not isinstance(rec, dict):
            rep.error(where, "is not an object")
            continue
        check_keys(rec, SIGNAL_KEYS, SIGNAL_REQUIRED, where, rep)

        node_id = rec.get("node_id")
        if not isinstance(node_id, str) or node_type_for(node_id) is None:
            rep.error(where, f"node_id {node_id!r} must be a valid node id")
        else:
            referenced.add(node_id)

    return referenced


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()

    data_dir: Path = args.data_dir
    if not data_dir.is_dir():
        print(f"FAIL  no such data directory: {data_dir}", file=sys.stderr)
        return 1

    rep = Report()
    declared: set[str] = set()
    referenced: set[str] = set()
    checked: list[str] = []

    for path in sorted(data_dir.glob("*.json")):
        name = path.name
        if name.startswith("nodes."):
            declared |= validate_nodes(path, rep)
        elif name.startswith("edges."):
            referenced |= validate_edges(path, rep)
        elif name == "compliance.json":
            referenced |= validate_compliance(path, rep)
        elif name == "bins.json":
            referenced |= validate_bins(path, rep)
        elif name == "signals.json":
            referenced |= validate_signals(path, rep)
        elif name in ("backtest.json", "eo14336.citation.json", "cascade_rules.json",
                      "audit.json", "audit.jsonl", "reroute.json", "jurisdictions.json",
                      "geo.json"):
            # Producer artifacts, not graph data. Each has an owner who defines its
            # shape; validating them here would mean duplicating that shape in two
            # places and letting the copies drift.
            #   backtest.json          a single object, Nikhil owns its shape
            #   eo14336.citation.json  a pinned citation, deliberately not graph data
            #   cascade_rules.json     Parth's risk thresholds, consumed by graph.ts
            #   audit.json/.jsonl      Nikhil's tamper-evident chain; ml/audit.py
            #                          --verify checks it far more strictly than a
            #                          shape check could, and a naive rewrite here
            #                          would break the hash chain
            #   reroute.json           AEGIS route output, emitted by ml/aegis.py --write
            #   jurisdictions.json     buyer-side rule table (WTO GPA parties), emitted by
            #                          ml/compliance.py --jurisdictions
            continue
        else:
            rep.warn(name, "not a file the contract names — nothing validated")
            continue
        checked.append(name)

    # Dangling refs are a warning: producers land at different times, so an edge
    # into a node nobody has written yet is normal until everyone has run.
    for node_id in sorted(referenced - declared):
        rep.warn("cross-file", f"{node_id} is referenced but not declared in any nodes.*.json")

    if not checked:
        print(f"FAIL  no contract files found in {data_dir}", file=sys.stderr)
        return 1

    print(f"checked {len(checked)} file(s) in {data_dir}: {', '.join(checked)}")
    print(f"        {len(declared)} node(s) declared, {len(referenced)} referenced")

    for warning in rep.warnings:
        print(f"WARN  {warning}")
    for error in rep.errors:
        print(f"FAIL  {error}", file=sys.stderr)

    if rep.errors:
        print(f"\n{len(rep.errors)} contract violation(s).", file=sys.stderr)
        return 1

    print(f"\nOK — contract satisfied ({len(rep.warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
