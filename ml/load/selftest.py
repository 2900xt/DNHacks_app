#!/usr/bin/env python3
"""Self-test for io_helpers + validate. Runs against a scratch dir, never web/data/.

    python3 ml/load/selftest.py

Exits non-zero on failure. Cheap enough to run before every push.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    if got == want:
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}: got {got!r}, want {want!r}")
        FAILURES.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory() as scratch:
        os.environ["CHOKEPOINT_DATA_DIR"] = scratch
        sys.path.insert(0, str(HERE))
        import io_helpers as io

        print("id helpers")
        check("normalize_key collapses punctuation",
              io.normalize_key("The United Laboratories (Inner Mongolia) Co., Ltd."),
              "the-united-laboratories-inner-mongolia-co-ltd")
        check("FEI wins over name",
              io.company_id(fei=3004446312, name="Aurobindo Pharma Limited"),
              ("company:fei:3004446312", "fei"))
        check("name-only falls back to fuzzy",
              io.company_id(name="SINOPHARM WEIQIDA"),
              ("company:name:sinopharm-weiqida", "fuzzy"))
        # The spelling trap: raw substring finds 5 of 8, squashed finds all 8.
        spellings = [
            "6-APA (6 AMINOPENICILLANIC ACID)", "6-AMINO PENICILLANIC ACID",
            "6-AMINOPENICILLANIC ACID (6-APA)", "6-AMINOPENICILLANIC ACID",
            "6-AMINO-PENICILLANIC ACID (6-APA)",
            "6-AMINO-PENICILLANIC ACID (6-APA) BULK DRUG SUBSTANCE",
        ]
        check("squash matches every 6-APA spelling",
              sum("AMINOPENICILLANIC" in io.squash(s) for s in spellings), len(spellings))
        check("raw substring match misses some (why squash exists)",
              sum("AMINOPENICILLANIC" in s for s in spellings) < len(spellings), True)

        print("insert + idempotency")
        io.write_nodes([io.node("company:name:sinopharm-weiqida", type="company",
                                label="SINOPHARM WEIQIDA", country="cn",
                                attrs={"dmf": 30779}, resolved_by="fuzzy")])
        io.write_nodes([io.node("company:name:sinopharm-weiqida", type="company",
                                label="SINOPHARM WEIQIDA", country="cn",
                                attrs={"dmf": 30779}, resolved_by="fuzzy")])
        rows = json.loads((io.DATA_DIR / "nodes.curated.json").read_text())
        check("writing the same node twice yields one row", len(rows), 1)
        check("critical defaults to False on insert", rows[0]["critical"], False)

        print("merge rule — None means don't touch")
        io.write_nodes([io.node("company:name:sinopharm-weiqida", type="company",
                                label="SINOPHARM WEIQIDA",
                                attrs={"operations": "API MANUFACTURE"})])
        row = json.loads((io.DATA_DIR / "nodes.curated.json").read_text())[0]
        check("country survives a write that omits it", row["country"], "cn")
        check("resolved_by survives", row["resolved_by"], "fuzzy")
        check("attrs shallow-merge", sorted(row["attrs"]), ["dmf", "operations"])

        print("edges")
        io.write_edges([io.edge("precursor:6-apa", "company:name:sinopharm-weiqida",
                                "produced_by", 2, "DMF 30779")])
        io.write_edges([io.edge("precursor:6-apa", "company:name:sinopharm-weiqida",
                                "produced_by", 2, "DMF 30779, 2Q2026")])
        edges = json.loads((io.DATA_DIR / "edges.curated.json").read_text())
        check("(src,dst,rel) is the identity — updates, not duplicates", len(edges), 1)
        check("citation updated in place", edges[0]["citation"], "DMF 30779, 2Q2026")

        print("contract enforcement")
        try:
            io.edge("precursor:6-apa", "api:ampicillin", "feeds", 3, "")
            check("layer 3 without citation raises", "no raise", "ContractError")
        except io.ContractError:
            check("layer 3 without citation raises", True, True)
        try:
            io.compliance("country:cn", taa_pass=False, evidence={})
            check("compliance without evidence raises", "no raise", "ContractError")
        except io.ContractError:
            check("compliance without evidence raises", True, True)

        print("rollback leaves the file intact")
        before = (io.DATA_DIR / "nodes.curated.json").read_text()
        try:
            # type contradicts the id — validate.py must reject it.
            io.write_nodes([{"id": "drug:ampicillin", "type": "precursor",
                             "label": "Ampicillin", "country": None,
                             "critical": False, "attrs": {}, "resolved_by": None}])
            check("bad node rejected", "no raise", "ContractError")
        except io.ContractError:
            check("bad node rejected", True, True)
        check("file rolled back byte for byte",
              (io.DATA_DIR / "nodes.curated.json").read_text(), before)

        print("validator exits non-zero on a violation")
        bad = Path(scratch) / "bins.json"
        bad.write_text(json.dumps([{"id": "bin:a", "label": "A",
                                    "covers_drugs": ["amoxicillin"]}]))
        result = subprocess.run(
            [sys.executable, str(HERE / "validate.py"), "--data-dir", scratch],
            capture_output=True, text=True)
        check("bare covers_drugs name fails", result.returncode, 1)
        bad.unlink()

    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s): {', '.join(FAILURES)}", file=sys.stderr)
        return 1
    print("\nOK — all self-tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
