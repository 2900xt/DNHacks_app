#!/usr/bin/env python3
"""Idempotent writers for the Layer 2/3 JSON artifacts.

Every loader in this directory goes through here. There is no database
(decision 0004), so "upsert" means: read the file, merge by key, rewrite it.

    from io_helpers import write_nodes, write_edges, write_compliance

⚠️ The brief calls this file `io.py`. It cannot be: CPython preloads the stdlib
`io` module into `sys.modules` before any user code runs, so `import io` from a
loader returns the stdlib module and this one is unreachable by name. Renamed to
`io_helpers.py`; the API is exactly what the brief specifies.

Re-running any loader must not duplicate rows — you will re-run these a lot
tonight, and six loaders write to the same three files.

## The merge rule, and why it matters

**None (or an absent key) means "don't touch".** Each loader writes only what it
knows and leaves the rest alone:

    load_eo13944  ->  drug:amoxicillin   critical=True, attrs.eo13944_listed
    load_decrs    ->  company:...        country='cn', attrs.operations
    load_dmf      ->  company:...        attrs.dmf, attrs.dmf_status

Without that rule, whichever loader ran last would blank the other five's work.
`attrs` shallow-merges for the same reason.

Writes are atomic and validated: on a contract violation the previous file
contents are restored and the write raises, so `main` never carries a broken
artifact.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]

# Point CHOKEPOINT_DATA_DIR somewhere scratch while developing a loader, or a
# half-finished run will overwrite the committed artifacts.
DATA_DIR = Path(os.environ.get("CHOKEPOINT_DATA_DIR", REPO_ROOT / "web" / "data"))

NODES_PATH = DATA_DIR / "nodes.curated.json"
EDGES_PATH = DATA_DIR / "edges.curated.json"
COMPLIANCE_PATH = DATA_DIR / "compliance.json"

VALIDATOR = HERE / "validate.py"

NODE_FIELDS = ("id", "type", "label", "country", "critical", "attrs", "resolved_by")
EDGE_FIELDS = ("src", "dst", "rel", "layer", "citation")
COMPLIANCE_FIELDS = ("node_id", "taa_pass", "on_1260h", "evidence")

# None means "don't touch" on merge — but a brand new row still has to satisfy
# the contract, so these fill in on insert only.
NODE_DEFAULTS = {"critical": False, "attrs": {}}
EDGE_DEFAULTS: dict = {}
COMPLIANCE_DEFAULTS: dict = {}


class ContractError(RuntimeError):
    """The merged data violates the contract; the file has been rolled back."""


# --- id helpers -------------------------------------------------------------
# The node-id scheme is type:key, lowercase, ASCII, hyphen-separated.
# FEI wins. company:name: is the last resort and MUST be flagged fuzzy.


def normalize_key(value: str) -> str:
    """Lowercase, collapse every run of non-alphanumerics to one hyphen."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def company_id(*, fei: str | int | None = None, duns: str | int | None = None,
               name: str | None = None) -> tuple[str, str]:
    """Return (node_id, resolved_by). FEI first, then DUNS, then the fuzzy name.

    Callers should pass everything they have and let this pick — that is how the
    contract's "FEI wins" rule gets applied consistently across six loaders.
    """
    if fei not in (None, ""):
        return f"company:fei:{str(fei).strip()}", "fei"
    if duns not in (None, ""):
        return f"company:duns:{str(duns).strip()}", "duns"
    if name:
        return f"company:name:{normalize_key(name)}", "fuzzy"
    raise ValueError("company_id needs at least one of fei, duns or name")


def facility_id(fei: str | int) -> str:
    return f"facility:fei:{str(fei).strip()}"


def country_id(iso2: str) -> str:
    iso2 = iso2.strip().lower()
    if not re.fullmatch(r"[a-z]{2}", iso2):
        raise ValueError(f"country_id needs an ISO-2 code, got {iso2!r}")
    return f"country:{iso2}"


def drug_id(name: str) -> str:
    return f"drug:{normalize_key(name)}"


def api_id(name: str) -> str:
    return f"api:{normalize_key(name)}"


def squash(value: str) -> str:
    """Strip every non-alphanumeric and uppercase — for matching DMF SUBJECT.

    The register spells one molecule eight ways: '6-APA (6 AMINOPENICILLANIC
    ACID)', '6-AMINO PENICILLANIC ACID', '6-AMINOPENICILLANIC ACID (6-APA)'...
    Matching AMINOPENICILLANIC against squash(subject) finds all 8; matching the
    raw string finds 5 and loses ANTIBIOTICOS SA. Never match SUBJECT raw.
    """
    return re.sub(r"[^A-Z0-9]", "", value.upper())


# --- record builders --------------------------------------------------------


def node(id: str, *, type: str, label: str, country: str | None = None,
         critical: bool | None = None, attrs: dict | None = None,
         resolved_by: str | None = None) -> dict:
    """Build a node. Omitted fields stay None and will not overwrite on merge."""
    return {
        "id": id, "type": type, "label": label, "country": country,
        "critical": critical, "attrs": attrs, "resolved_by": resolved_by,
    }


def edge(src: str, dst: str, rel: str, layer: int, citation: str | None = None) -> dict:
    if layer == 3 and not (citation or "").strip():
        raise ContractError(f"layer 3 edge {src} --{rel}--> {dst} needs a citation")
    return {"src": src, "dst": dst, "rel": rel, "layer": layer, "citation": citation}


def compliance(node_id: str, *, taa_pass: bool | None = None,
               on_1260h: bool | None = None, evidence: dict | None = None) -> dict:
    if not evidence:
        raise ContractError(f"compliance row for {node_id} needs evidence — every "
                            "determination carries its citation (decision 0003)")
    return {"node_id": node_id, "taa_pass": taa_pass,
            "on_1260h": on_1260h, "evidence": evidence}


# --- merge ------------------------------------------------------------------


def _pick(old, new):
    """New wins, unless it is None — None means 'this loader has no opinion'."""
    return old if new is None else new


def _merge_record(old: dict, new: dict, fields: Iterable[str]) -> dict:
    merged = dict(old)
    for field in fields:
        if field in ("attrs", "evidence", "payload"):
            continue
        if field in new:
            merged[field] = _pick(old.get(field), new[field])
    for nested in ("attrs", "evidence"):
        if nested in fields and new.get(nested):
            merged[nested] = {**(old.get(nested) or {}), **new[nested]}
    return merged


def _upsert(existing: list[dict], incoming: Iterable[dict], key, fields,
            defaults: dict | None = None) -> list[dict]:
    defaults = defaults or {}
    by_key: dict = {key(r): r for r in existing}
    order: list = list(by_key)
    for rec in incoming:
        k = key(rec)
        if k in by_key:
            by_key[k] = _merge_record(by_key[k], rec, fields)
        else:
            fresh = {f: rec.get(f) for f in fields}
            for field, fallback in defaults.items():
                if fresh.get(field) is None:
                    fresh[field] = fallback
            by_key[k] = fresh
            order.append(k)
    return [by_key[k] for k in order]


# --- file io ----------------------------------------------------------------


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    text = path.read_text().strip()
    return json.loads(text) if text else []


def _strip_nulls(rows: list[dict]) -> list[dict]:
    """Drop keys whose value is None before serialising.

    The app's types declare optionals as `country?: string`, which under
    `strict: true` means `string | undefined` — **not** `string | null`. With
    `resolveJsonModule`, a literal null in the JSON types as `null` and will not
    assign to those fields. Omitting the key is the shape the contract actually
    declares, and it means the same thing to the merge rule (absent == "no
    opinion"), so nothing downstream changes.
    """
    return [{k: v for k, v in row.items() if v is not None} for row in rows]


def _dump(rows: list[dict]) -> str:
    return json.dumps(_strip_nulls(rows), indent=2, ensure_ascii=False) + "\n"


def run_validate() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--data-dir", str(DATA_DIR)],
        capture_output=True, text=True,
    )


def _write_and_validate(path: Path, rows: list[dict]) -> int:
    """Write atomically, validate the whole data dir, roll back on violation."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    previous = path.read_text() if path.exists() else None

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(_dump(rows))
    tmp.replace(path)

    result = run_validate()
    if result.returncode != 0:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(previous)
        raise ContractError(
            f"{path.name} rolled back — contract violation:\n{result.stderr.strip()}"
        )
    return len(rows)


def read_nodes() -> list[dict]:
    """Current curated nodes. Loaders that annotate existing nodes (TAA marks
    countries, 1260H marks companies) read this to know what is in the graph."""
    return _read(NODES_PATH)


def write_nodes(nodes: Iterable[dict]) -> int:
    rows = _upsert(_read(NODES_PATH), nodes, lambda r: r["id"], NODE_FIELDS,
                   NODE_DEFAULTS)
    return _write_and_validate(NODES_PATH, rows)


def write_edges(edges: Iterable[dict]) -> int:
    # Edges have no id in the contract; identity is (src, dst, rel).
    rows = _upsert(_read(EDGES_PATH), edges,
                   lambda r: (r["src"], r["dst"], r["rel"]), EDGE_FIELDS,
                   EDGE_DEFAULTS)
    return _write_and_validate(EDGES_PATH, rows)


def write_compliance(rows_in: Iterable[dict]) -> int:
    rows = _upsert(_read(COMPLIANCE_PATH), rows_in,
                   lambda r: r["node_id"], COMPLIANCE_FIELDS,
                   COMPLIANCE_DEFAULTS)
    return _write_and_validate(COMPLIANCE_PATH, rows)
