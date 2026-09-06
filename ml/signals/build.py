"""Build `web/data/signals.json` from all Layer 1c feeds.

    python3 -m ml.signals.build              # use pinned caches where present
    python3 -m ml.signals.build --refresh    # re-fetch everything

Writes exactly one file, `web/data/signals.json`, which is Parth's file in the
data contract. Never writes to anyone else's.

Feeds, and why each is here:
  Federal Register  live, no key. Company + country nodes only.
  OASIS             bulk zip, no key. Facility nodes, cGMP-weighted.
  FDA Inspection    undocumented Qlik route. Facility nodes, STATE not event.
  GDELT             deliberately absent - it is cut #6. 0 mentions of our four
                    antibiotics across 1,440 cached articles; its value is one
                    narrated line about 2022 Shanghai, not a loader.
"""

from __future__ import annotations

import sys

from . import fda_inspections, federal_register, oasis
from .common import LoaderError, write_signals

#: The signals that must exist or the demo has no named evidence.
ANCHORS = {
    "facility:fei:3004446312": "Aurobindo Pharma Limited — OAI 2025-09-05",
    "facility:fei:3004497364": "Centrient Pharmaceuticals India — OAI 2026-01-27",
    "facility:fei:3003196232": "CSPC Zhongnuo — amoxicillin refused 2026-07-24",
}


def main(refresh: bool = False) -> int:
    all_signals = []
    failed = []

    for name, fn in (
        ("federal register", lambda: federal_register.load()),
        ("oasis", lambda: oasis.load()),
        ("fda inspections", lambda: fda_inspections.load(refresh=refresh)),
    ):
        print(f"{name}:")
        try:
            rows = fn()
            all_signals += rows
            print(f"  -> {len(rows):,} signals")
        except LoaderError as e:
            failed.append((name, e))
            print(f"  !! FAILED: {e}")

    if not all_signals:
        print("\nno signals from any feed — refusing to write an empty file")
        return 1

    path = write_signals(all_signals)
    print(f"\nwrote {len(all_signals):,} signals -> {path.relative_to(path.parents[2])}")

    by_kind: dict[str, int] = {}
    for s in all_signals:
        by_kind[s.kind] = by_kind.get(s.kind, 0) + 1
    for kind, n in sorted(by_kind.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>6,}  {kind}")

    print("\nanchor check:")
    present = {s.node_id for s in all_signals}
    missing = [k for k in ANCHORS if k not in present]
    for node, label in ANCHORS.items():
        print(f"  [{'OK ' if node in present else 'MISSING'}] {label}")

    if failed:
        print(f"\n{len(failed)} feed(s) failed: {', '.join(n for n, _ in failed)}")
    if missing:
        print(f"{len(missing)} anchor(s) missing — the demo has no named evidence")
    return 1 if (failed or missing) else 0


if __name__ == "__main__":
    sys.exit(main(refresh="--refresh" in sys.argv))
