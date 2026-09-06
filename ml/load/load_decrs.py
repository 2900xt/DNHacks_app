#!/usr/bin/env python3
"""Layer 2 — FDA DECRS establishment register (country + FEI for our companies).

    python3 ml/load/load_decrs.py

DECRS is the only public file that says *where* a drug-making facility is. It has
**no drug, product, NDC or ingredient column at all** — it says *that* a firm makes
APIs, never *which* one. That is why the per-drug denominator comes from the DMF
register's SUBJECT column instead (see load_dmf.py).

What this loader does: match our 6-APA DMF holders to DECRS firms by normalised
name, and upgrade the company nodes with a real country at layer 2 (superseding the
curated layer-3 attribution) plus FEI, DUNS and operations.

## Traps, all confirmed against the live file

* **Bot-gated.** `accessdata.fda.gov` serves an apology page without a browser
  User-Agent. `www.fda.gov` does not — do not spread the "FDA blocks bots" claim
  wider than this host.
* **Every row has a trailing tab**, so a naive tab-delimited read emits a 15th
  field under a null key.
* 🔴 **The first column is named `' FEI_NUMBER'` — with a leading space.**
  `row["FEI_NUMBER"]` raises KeyError. Field names are stripped below.
* 🔴 **146,104 of the values carry their own surrounding whitespace** — `'DSP '`,
  `'3004446312 '`. Stripped centrally in `read_rows()` rather than at each call
  site, because one forgotten `.strip()` silently breaks a name match.
* 🔴 **FEI width is inconsistent.** 8,543 rows are zero-padded to 10 chars, 1,693
  are a bare 7, and 200 are empty — so the same plant can appear as `0001234567`
  and `1234567`, and minting `company:fei:` ids straight from the column would
  create two nodes for one establishment. `normalize_fei()` strips leading zeros.
  Aurobindo's 3004446312 is genuinely 10 digits and is unaffected, so it still
  matches the `company:fei:3004446312` node Nikhil emits.
* **`EXPIRATION_DATE` is `12/31/2026` on every one of the 10,436 rows.** It is an
  annual snapshot, not a live feed, whatever FDA says about daily updates. Never
  present DECRS as real-time.
* **`REGISTRANT_NAME` differs from `FIRM_NAME` on 33.3% of rows** — the registrant
  is the legal filer, the firm is the plant. That difference is the foreign-
  ownership fact, so both go on the node.

## The name match is the weak link, and it is measured, not assumed

DMF holder -> DECRS firm is the join the entity-resolution benchmark exists to
beat. This loader reports its own exact and normalised hit rate so the number on
stage comes from a run, not from memory.
"""

from __future__ import annotations

import collections
import csv
import re
import sys
import urllib.request
import zipfile
from io import StringIO
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import io_helpers as io  # noqa: E402

DECRS_URL = "https://www.accessdata.fda.gov/cder/drls_reg.zip"
DECRS_SOURCE = "FDA DECRS drls_reg"
CACHE = HERE.parent / "cache" / "drls_reg.zip"
MEMBER = "drls_reg.txt"

# accessdata.fda.gov 302s to an apology page that then 404s without this.
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

ISO3_TO_ISO2 = {
    "AUT": "at", "IND": "in", "CHN": "cn", "USA": "us", "ITA": "it", "DEU": "de",
    "JPN": "jp", "GBR": "gb", "IRL": "ie", "NLD": "nl", "CHE": "ch", "FRA": "fr",
    "ISR": "il", "KOR": "kr", "SGP": "sg", "CAN": "ca", "MEX": "mx", "BRA": "br",
    "ESP": "es", "PRT": "pt", "BEL": "be", "DNK": "dk", "SWE": "se", "POL": "pl",
    "HUN": "hu", "SVN": "si", "HRV": "hr", "AUS": "au", "NZL": "nz", "TWN": "tw",
}
COUNTRY_LABELS = {"at": "Austria", "in": "India", "cn": "China", "us": "United States",
                  "it": "Italy", "de": "Germany", "jp": "Japan", "es": "Spain"}

ADDRESS_ISO3 = re.compile(r"\(([A-Z]{3})\)\s*$")


def fetch() -> Path:
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(DECRS_URL, headers={"User-Agent": BROWSER_UA})
        with urllib.request.urlopen(req, timeout=180) as resp:
            CACHE.write_bytes(resp.read())
    return CACHE


def normalize_fei(value: str | None) -> str | None:
    """Canonical FEI: no surrounding space, no leading zeros.

    The file mixes widths — 8,543 rows carry a 10-char zero-padded FEI, 1,693
    carry a bare 7-char one, and 200 are empty. So the *same* establishment can be
    written `0001234567` here and `1234567` elsewhere, and minting node ids
    straight from the column would produce two `company:fei:` nodes for one plant.
    Stripping leading zeros collapses both to one id, and leaves genuinely 10-digit
    numbers (Aurobindo's 3004446312) untouched.
    """
    fei = (value or "").strip().lstrip("0")
    return fei or None


def read_rows() -> list[dict]:
    raw = zipfile.ZipFile(fetch()).read(MEMBER).decode("utf-8", errors="replace")
    reader = csv.DictReader(StringIO(raw), delimiter="\t")
    rows = []
    for rec in reader:
        # Three defects in one line of the source file:
        #  * the first column is named ' FEI_NUMBER' — with a leading space, so
        #    rec["FEI_NUMBER"] raises KeyError. Strip the key.
        #  * every row ends in a trailing tab, so DictReader emits a 15th field
        #    under a null key. Drop it.
        #  * 146,104 of the values carry their own surrounding whitespace. Strip
        #    centrally rather than hoping every call site remembers.
        rows.append({k.strip(): (v.strip() if isinstance(v, str) else v)
                     for k, v in rec.items() if k is not None})
    return rows


def country_of(row: dict) -> tuple[str | None, str | None]:
    m = ADDRESS_ISO3.search(row.get("ADDRESS") or "")
    if not m:
        return None, None
    iso3 = m.group(1)
    return ISO3_TO_ISO2.get(iso3), iso3


def main() -> int:
    rows = read_rows()
    api_makers = [r for r in rows if "API MANUFACTURE" in (r.get("OPERATIONS") or "")]
    by_country = collections.Counter(
        iso3 for r in api_makers if (iso3 := country_of(r)[1]))
    cn_in = by_country["CHN"] + by_country["IND"]

    print(f"{DECRS_SOURCE} — {len(rows):,} establishments, "
          f"{len(by_country)} countries")
    print(f"  {len(api_makers):,} do API MANUFACTURE; "
          f"CHN {by_country['CHN']} + IND {by_country['IND']} = {cn_in} "
          f"({cn_in / len(api_makers):.0%})")
    print("  neither China nor India is TAA-designated (FAR 25.003)")
    print("  ⚠️ this file is a live download and drifts — the Sep 4 snapshot in the "
          "brain said 10,236 / 2,473 / 43%. Quote a run, not a memory.")

    # Index by normalised firm name. Never substring-match.
    by_name: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        by_name[io.normalize_key(r.get("FIRM_NAME") or "")].append(r)

    nodes, edges = [], []
    exact = 0
    targets = [n for n in io.read_nodes() if n["type"] == "company"]
    if not targets:
        sys.exit("FAIL: no company nodes to annotate. Run load_dmf.py first — "
                 "load_precursor_edges -> load_dmf -> load_decrs -> load_taa -> load_1260h")

    for node in targets:
        key = node["id"].split("company:name:")[-1]
        matches = by_name.get(key, [])
        if not matches:
            print(f"  no DECRS match: {node['label']}")
            continue
        exact += 1
        rec = matches[0]
        iso2, iso3 = country_of(rec)
        fei = normalize_fei(rec.get("FEI_NUMBER"))
        registrant = rec.get("REGISTRANT_NAME") or ""
        firm = rec.get("FIRM_NAME") or ""

        attrs = {
            "fei": fei,
            "duns": (rec.get("DUNS_NUMBER") or "") or None,
            "decrs_firm_name": firm,
            "decrs_registrant_name": registrant,
            "foreign_ownership_note": (
                f"registrant '{registrant}' differs from plant '{firm}'"
                if registrant and registrant != firm else None),
            "operations": (rec.get("OPERATIONS") or "") or None,
            "decrs_address_iso3": iso3,
            "decrs_sites": len(matches),
            "decrs_source": DECRS_SOURCE,
            "decrs_snapshot": "annual snapshot — EXPIRATION_DATE is 12/31/2026 on "
                              "every row; not a live feed",
        }
        attrs = {k: v for k, v in attrs.items() if v is not None}

        # resolved_by stays 'fuzzy': the FEI was reached BY a name match, so the
        # resolution is only as good as that match. Recording the FEI is useful;
        # claiming exactness would not be.
        nodes.append(io.node(node["id"], type="company", label=node["label"],
                             country=iso2, attrs=attrs, resolved_by="fuzzy"))

        if iso2:
            cid = io.country_id(iso2)
            nodes.append(io.node(cid, type="country",
                                 label=COUNTRY_LABELS.get(iso2, iso2.upper()),
                                 country=iso2,
                                 attrs={"source": DECRS_SOURCE}))
            edges.append(io.edge(
                node["id"], cid, "incorporated_in", 2,
                f"{DECRS_SOURCE} — FEI {fei}, '{firm}', address ends ({iso3}). "
                f"{DECRS_URL}"))

    io.write_nodes(nodes)
    if edges:
        io.write_edges(edges)

    rate = exact / len(targets) if targets else 0
    print(f"\n  matched {exact}/{len(targets)} company nodes on normalised name "
          f"({rate:.0%})")
    print("  the unmatched ones are the entity-resolution problem, not a bug here")
    return 0


if __name__ == "__main__":
    sys.exit(main())
