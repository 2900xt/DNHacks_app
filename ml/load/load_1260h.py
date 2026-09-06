#!/usr/bin/env python3
"""Layer 2 — DoD 1260H Chinese military companies (the BIOSECURE flag).

    python3 ml/load/load_1260h.py

Parses the **structured XML** rendering of 91 FR 35189, not the plain text.
`project/datasets/layer2-official-lists.md` §5.4 asks whether `full_text_xml_url`
removes the need for the plain-text record grammar. **It does**, and it deletes
both documented traps outright:

  * `[[Page 35190]]` page breaks are a `PRTPAGE` element, not inline noise, so
    they cannot land mid-entity.
  * Justifications are their own paragraphs starting with a bullet, so nothing has
    to guess where a wrapped name ends.

Entity vs. justification is decided by "does this paragraph start with a bullet",
NOT by element type — some entity names come through as `P` rather than `FP`.

## Counts — these differ from the plain-text parse

The XML gives **80 designated parents, each with exactly one justification
bullet**, strictly alphabetical. The plain-text parse reported 77 parents with
three entities "carrying two bullets"; those three are cases where the entity name
also appears *inside its own justification sentence*, which the text parser counted
as a second occurrence. See the loader's own integrity checks below.

## Do not oversell this on stage

1260H is a **defence-industrial list, not a pharma list.** Overlap with FDA-
registered API makers is small by construction, and there are **zero exact matches**
to our 6-APA holders. WuXi AppTec and BGI are designated because of BIOSECURE, not
because they make 6-APA. Conversely **Sinopharm Weiqida makes 6-APA, is state-owned,
and is NOT on 1260H** — state ownership and 1260H designation are different things.
"""

from __future__ import annotations

import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import io_helpers as io  # noqa: E402

XML_URL = ("https://www.federalregister.gov/documents/full_text/xml/"
           "2026/06/10/2026-11571.xml")
FR_DOC = "2026-11571"
FR_CITE = "91 FR 35189, Jun 10 2026"
RECORD_URL = ("https://www.federalregister.gov/documents/2026/06/10/2026-11571/"
              "notice-of-availability-of-designation-of-chinese-military-companies")
CACHE = HERE.parent / "cache" / "1260h.xml"

DESIGNATE_ANCHOR = "qualify for designation"
REMOVE_ANCHOR = "should be removed"
END_ANCHOR = "list of entities designated"

# Rejoin comma-split fragments that are just a legal suffix, optionally with a
# trailing acronym: 'BGI Genomics Co.' + 'Ltd. (BGI)' is one company, not two.
SUFFIX = re.compile(r"^(Ltd|Inc|Co|Corp|LLC|Limited|PLC|L\.P|S\.A|GmbH|Pte)\.?"
                    r"(\s*\(.*?\))?\.?$", re.I)


def fetch() -> Path:
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(
            XML_URL, headers={"User-Agent": "Mozilla/5.0 (CHOKEPOINT/DNHacks research)"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            CACHE.write_bytes(resp.read())
    return CACHE


def paragraphs() -> list[str]:
    root = ET.parse(fetch()).getroot()
    return [re.sub(r"\s+", " ", "".join(el.itertext()).strip())
            for el in root.iter() if el.tag in ("P", "FP")]


def split_subsidiaries(blob: str) -> list[str]:
    parts = [p.strip() for p in re.split(r",\s*(?:and\s+)?", blob) if p.strip()]
    out: list[str] = []
    for part in parts:
        if out and SUFFIX.match(part):
            out[-1] += ", " + part
        else:
            out.append(part)
    return out


def parse() -> tuple[list[dict], list[str]]:
    els = paragraphs()
    start = next(i for i, x in enumerate(els) if DESIGNATE_ANCHOR in x)
    stop = next(i for i, x in enumerate(els) if REMOVE_ANCHOR in x)

    entities, bullets = [], 0
    for para in els[start + 1:stop]:
        if para.startswith("•"):
            bullets += 1
            if entities:
                entities[-1]["justification"] = para.lstrip("• ").strip()
        else:
            name = para
            subs: list[str] = []
            m = re.search(r"\(and .*?subsidiar\w*:(.*?)\)\s*$", name)
            if m:
                subs = split_subsidiaries(m.group(1))
                name = name[:m.start()].strip()
            alias = None
            a = re.search(r"\(([^()]*)\)\s*$", name)
            if a:
                alias = a.group(1).strip()
                name = name[:a.start()].strip()
            entities.append({"entity": name, "alias": alias,
                             "subsidiaries": subs, "justification": None})

    tail = [x for x in els[stop + 1:] if not x.startswith("•")]
    end = next((i for i, x in enumerate(tail) if END_ANCHOR in x), len(tail))
    removals = [x for x in tail[:end] if x]

    # Integrity checks. The notice is strictly alphabetical; a parse that has
    # split or merged a name breaks the ordering.
    names = [e["entity"] for e in entities]
    key = lambda s: re.sub(r"^The ", "", s).upper()
    if names != sorted(names, key=key):
        bad = next(a for a, b in zip(names, sorted(names, key=key)) if a != b)
        sys.exit(f"FAIL: designations are not alphabetical at {bad!r} — a name was "
                 f"split or merged")
    missing = [e["entity"] for e in entities if not e["justification"]]
    if missing:
        sys.exit(f"FAIL: {len(missing)} entity(ies) have no justification bullet — "
                 f"the entity/bullet pairing is wrong: {missing[:3]}")
    if bullets != len(entities):
        sys.exit(f"FAIL: {bullets} bullets for {len(entities)} entities — expected 1:1")
    return entities, removals


def main() -> int:
    entities, removals = parse()
    subs_total = sum(len(e["subsidiaries"]) for e in entities)
    print(f"DoD 1260H — {FR_CITE} (FR doc {FR_DOC}), parsed from structured XML")
    print(f"  {len(entities)} designated parents, each with exactly 1 justification")
    print(f"  {sum(1 for e in entities if e['subsidiaries'])} carry a subsidiary list "
          f"-> {subs_total} named subsidiaries")
    print(f"  {len(removals)} removals")
    print("  integrity: strictly alphabetical, 1:1 entity-to-bullet")

    # Exact and normalised lookup over parents + subsidiaries.
    listed: dict[str, tuple[str, str]] = {}
    for e in entities:
        listed[io.normalize_key(e["entity"])] = (e["entity"], "parent")
        if e["alias"]:
            listed.setdefault(io.normalize_key(e["alias"]), (e["entity"], "alias"))
        for sub in e["subsidiaries"]:
            listed.setdefault(io.normalize_key(sub), (f"{sub} ({e['entity']})", "subsidiary"))

    compliance, hits = [], []
    for node in io.read_nodes():
        if node["type"] != "company":
            continue
        key = node["id"].split("company:name:")[-1]
        match = listed.get(key)
        on_list = match is not None
        if on_list:
            hits.append(node["id"])
        compliance.append(io.compliance(
            node["id"], on_1260h=on_list,
            evidence={
                "on_1260h_reason": (
                    f"matches 1260H {match[1]} '{match[0]}'" if on_list else
                    f"not among the {len(entities)} designated parents or "
                    f"{subs_total} named subsidiaries"),
                "matched_entity": match[0] if on_list else None,
                "fr_doc": FR_DOC,
                "fr_citation": FR_CITE,
                "url": RECORD_URL,
                "designated_parents": len(entities),
                "named_subsidiaries": subs_total,
                "match_method": "exact on normalised name — no fuzzy matching",
            }))

    io.write_compliance(compliance)
    print(f"\n  on_1260h written for {len(compliance)} company node(s); "
          f"{len(hits)} on the list")
    print("  0 matches is the expected, honest result: 1260H is a defence list, "
          "not a pharma list")
    return 0


if __name__ == "__main__":
    sys.exit(main())
