#!/usr/bin/env python3
"""Layer 2 — TAA designated countries, from FAR 25.003.

    python3 ml/load/load_taa.py

FAR 25.003 defines "designated country" as four statutory buckets in prose, not a
table. Scraped and parsed to 132 rows across WTO GPA / FTA / least developed /
Caribbean Basin. Countries appear in more than one bucket, so **132 is rows, not
distinct countries** — dedupe before quoting a country count.

Writes `compliance.taa_pass` for every country node in the graph, each with its
citation. A PASS/FAIL with no source is what decision 0003 rules out.

## Three traps, all of which produce a WRONG pass/fail

1. **The lists read "A, B, or C".** A plain comma split leaves "or United Kingdom"
   and the UK reads as NOT designated. It is designated. Asserted below.
2. **China and India are absent, and that is the demo's central claim.** Asserted,
   so a change to the FAR breaks this loader loudly instead of silently flipping
   what we say on stage.
3. **The US is not on the list either, and that is NOT a failure.** US goods pass
   as *domestic end products* under a different branch of FAR 25. Any table that
   renders `USA -> designated: NO` is actively misleading, so US-like nodes get
   taa_pass=None and a reason that says which branch applies.
"""

from __future__ import annotations

import html
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import io_helpers as io  # noqa: E402

FAR_URL = "https://www.acquisition.gov/far/25.003"
FAR_CITE = "FAR 25.003, definition of 'designated country'"
CACHE = HERE.parent / "cache" / "far-25003.html"

# The label carries its own parenthetical acronym — "...Agreement (WTO GPA)
# country (Armenia, ...)" — so anchor on the prose, then take the list that
# follows " country (".
BUCKETS = [
    ("wto_gpa", "World Trade Organization Government Procurement Agreement"),
    ("fta", "Free Trade Agreement"),
    ("least_developed", "A least developed country"),
    ("caribbean_basin", "Caribbean Basin country"),
]

# ISO-2 for the countries our graph actually reaches. The full crosswalk is ~20
# rows and nobody had written it; this is the subset the amoxicillin subgraph needs.
ISO2 = {
    "austria": "at", "india": "in", "china": "cn", "spain": "es",
    "italy": "it", "germany": "de", "japan": "jp", "united states": "us",
    "united kingdom": "gb", "ireland": "ie", "netherlands": "nl",
    "switzerland": "ch", "france": "fr", "israel": "il", "korea": "kr",
    "singapore": "sg", "canada": "ca", "mexico": "mx", "brazil": "br",
}


def fetch() -> str:
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(
            FAR_URL, headers={"User-Agent": "Mozilla/5.0 (CHOKEPOINT/DNHacks research)"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            CACHE.write_bytes(resp.read())
    return CACHE.read_text(encoding="utf-8", errors="replace")


def plain_text(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)))


def balanced_list(text: str, anchor: str) -> str:
    """Return the country list following `anchor`, respecting nested parens.

    Taiwan's entry is: Taiwan (known in the WTO as "the Separate Customs Territory
    of Taiwan, Penghu, Kinmen and Matsu (Chinese Taipei)"). A non-greedy \\(.*?\\)
    stops at the first close-paren and truncates the whole bucket.
    """
    i = text.find(anchor)
    if i < 0:
        return ""
    j = text.find(" country (", i)
    if j < 0:
        return ""
    start = j + len(" country (")
    depth = 1
    for k in range(start, len(text)):
        if text[k] == "(":
            depth += 1
        elif text[k] == ")":
            depth -= 1
            if depth == 0:
                return text[start:k]
    return ""


def split_countries(blob: str) -> list[str]:
    """Split 'A, B, or C' on top-level commas only.

    Depth-tracking matters: splitting Taiwan's gloss on its internal commas
    invents 'Penghu' and 'Kinmen and Matsu' as countries. And the FAR itself
    contains a 'Austria,,' double-comma typo, which yields an empty part.
    """
    parts, depth, buf = [], 0, []
    for ch in blob:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))

    out = []
    for part in parts:
        part = re.sub(r"^\s*(?:or|and)\s+", "", part.strip())
        part = re.sub(r"\s*\(.*\)\s*$", "", part).strip().strip('"“”')
        if part:
            out.append(part)
    return out


def main() -> int:
    text = plain_text(fetch())
    start = text.find("Designated country means")
    if start < 0:
        sys.exit("FAIL: could not find the 'Designated country means' definition in FAR 25.003")
    section = text[start:start + 8000]

    rows: list[tuple[str, str]] = []
    for basis, anchor in BUCKETS:
        blob = balanced_list(section, anchor)
        if not blob:
            sys.exit(f"FAIL: bucket {basis!r} not found — FAR 25.003 layout changed")
        for country in split_countries(blob):
            rows.append((country, basis))
        print(f"  {basis:<16} {sum(1 for _, b in rows if b == basis):>3}")

    designated = {c.lower() for c, _ in rows}
    print(f"  {'TOTAL ROWS':<16} {len(rows):>3}   distinct: {len(designated)}")

    # Assertions: these are the demo's central claims. Break loudly, not silently.
    for absent in ("china", "india"):
        if absent in designated:
            sys.exit(f"FAIL: {absent!r} is now TAA-designated — the demo's central "
                     f"claim has changed. Do not ship until this is re-checked.")
    if "united kingdom" not in designated:
        sys.exit("FAIL: United Kingdom missing — the 'A, B, or C' split trap has "
                 "regressed and countries are being lost.")
    print("  asserted: China absent, India absent, United Kingdom present")

    basis_of: dict[str, list[str]] = {}
    for country, basis in rows:
        basis_of.setdefault(country.lower(), []).append(basis)

    nodes, compliance = [], []
    for node in io.read_nodes():
        if node["type"] != "country":
            continue
        iso2 = node.get("country")
        name = next((n for n, code in ISO2.items() if code == iso2), None)
        bases = basis_of.get(name or "", [])

        if iso2 == "us":
            # Absent from the 132, and that is not a failure.
            taa_pass, reason = None, ("US goods pass as domestic end products under "
                                      "FAR 25.1, not via the designated-country list")
        elif name is None:
            taa_pass, reason = None, f"no ISO-2 -> FAR country-name crosswalk row for {iso2!r}"
        else:
            taa_pass = bool(bases)
            reason = (f"{node['label']} is a designated country ({', '.join(bases)}) "
                      f"under {FAR_CITE}") if taa_pass else \
                     (f"{node['label']} is not a TAA-designated country under {FAR_CITE}")

        nodes.append(io.node(node["id"], type="country", label=node["label"],
                             attrs={"taa_designated": taa_pass,
                                    "taa_basis": bases or None}))
        compliance.append(io.compliance(
            node["id"], taa_pass=taa_pass,
            evidence={"reason": reason, "far": "25.003", "url": FAR_URL,
                      "designated_rows": len(rows),
                      "designated_distinct": len(designated),
                      "basis": bases or None}))

    if not compliance:
        sys.exit("FAIL: no country nodes in the graph to annotate. Country nodes come "
                 "from load_dmf.py — run the loaders in order:\n"
                 "  load_precursor_edges -> load_dmf -> load_taa -> load_1260h")

    io.write_nodes(nodes)
    io.write_compliance(compliance)
    verdict = {c["node_id"]: c["taa_pass"] for c in compliance}
    print(f"\n  compliance written for {len(compliance)} country node(s): {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
