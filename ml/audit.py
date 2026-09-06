"""Audit trail — a tamper-evident record of every decision an agent makes.

Called BLACKBOX internally; on stage it is the **audit trail**, never "BlackBox"
(EXECUTION-PLAN.md §3 conflict C1).

Why this exists
---------------
decisions/0003 requires that every flagged node can show, on screen, the specific
rule and the specific signals that fired it. A reasoning agent that picks its own
parameters cannot satisfy that by construction -- so it has to satisfy it by
*record*. This module is that record.

What makes it an audit trail rather than a log
----------------------------------------------
Every entry carries the hash of the entry before it. Change one field of one
historical entry, or delete an entry from the middle, and every hash after it
stops matching. `verify()` proves the chain is intact, and can say exactly which
sequence number broke. A log you can quietly edit is not evidence.

Usage
-----
    from audit import AuditLog

    log = AuditLog(run_id="reroute-amoxicillin")

    with log.step("assess", inputs={"node": "precursor:6-apa"}) as s:
        s.observe("cascade", {"affected": 787, "drugs": 6})
        s.params({"risk_weight": 0.7, "lead_time_weight": 0.3},
                 why="No public capacity data, so lead time is down-weighted "
                     "relative to concentration risk. See DATA.md Layer 1d.")
        s.action("rank_alternates", {"candidates": 8})
        s.result({"chosen": "company:name:antibioticos-sa", "score": 0.71})

    log.close()

CLI
---
    python ml/audit.py --verify          # prove the chain is intact
    python ml/audit.py --export          # write web/data/audit.json for the app
    python ml/audit.py --selftest        # includes a tamper-detection test
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "web" / "data"
LOG_PATH = DATA_DIR / "audit.jsonl"
EXPORT_PATH = DATA_DIR / "audit.json"

GENESIS = "0" * 64
SCHEMA_VERSION = 1

# Anything matching these substrings is replaced before it reaches disk. The audit
# trail is committed to git and shipped to Vercel -- decision 0004 -- so a key that
# lands here is a key that is published.
_SECRET_HINTS = ("api_key", "apikey", "token", "secret", "password", "authorization")
_REDACTED = "[redacted]"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _canonical(entry: dict) -> str:
    """Deterministic serialisation. Key order and separators must not vary, or the
    same entry hashes differently on a different machine and the chain 'breaks'
    for a reason that has nothing to do with tampering."""
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash(prev_hash: str, body: dict) -> str:
    return hashlib.sha256((prev_hash + _canonical(body)).encode()).hexdigest()


def redact(value: Any) -> Any:
    """Recursively blank anything that looks like a credential."""
    if isinstance(value, dict):
        return {
            k: (_REDACTED if any(h in k.lower() for h in _SECRET_HINTS) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class Step:
    """One decision. Populated through the context manager, written once on exit."""

    def __init__(self, log: "AuditLog", phase: str, inputs: dict | None) -> None:
        self._log = log
        self.phase = phase
        self.inputs = redact(inputs or {})
        self.observations: list[dict] = []
        self.parameters: dict | None = None
        self.rationale: str | None = None
        self.actions: list[dict] = []
        self.outcome: dict | None = None
        self.error: str | None = None
        self._t0 = time.perf_counter()

    def observe(self, what: str, value: Any) -> "Step":
        """What the agent saw. Record this even when it changes nothing — 'the agent
        looked and found no signal' is itself an auditable decision."""
        self.observations.append({"what": what, "value": redact(value)})
        return self

    def params(self, values: dict, *, why: str) -> "Step":
        """The tuned parameters AND the reasoning behind them.

        `why` is required and must be non-empty. The whole claim of a reasoning
        agent is that it can justify its parameters where a formula cannot; a
        parameter set with no stated reason is the thing we are trying not to ship.
        """
        if not why or not why.strip():
            raise ValueError(
                "params(why=...) must explain the choice. An unexplained parameter "
                "is exactly what decisions/0003 rules out."
            )
        self.parameters = redact(values)
        self.rationale = why.strip()
        return self

    def action(self, kind: str, detail: dict | None = None) -> "Step":
        self.actions.append({"kind": kind, "detail": redact(detail or {})})
        return self

    def result(self, outcome: dict) -> "Step":
        self.outcome = redact(outcome)
        return self


class AuditLog:
    """Append-only, hash-chained. One file per run_id is not required — many runs
    can share a file and are separated by `run_id`."""

    def __init__(self, run_id: str | None = None, path: Path | str = LOG_PATH,
                 actor: str = "agent") -> None:
        self.run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
        self.actor = actor
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq, self._prev = self._resume()
        self._closed = False
        self._record("run_start", {"schema": SCHEMA_VERSION})

    def _resume(self) -> tuple[int, str]:
        """Continue an existing chain rather than starting a new one, so restarting
        the agent does not silently fork the trail."""
        if not self.path.exists():
            return 0, GENESIS
        last = None
        with self.path.open() as fh:
            for line in fh:
                if line.strip():
                    last = json.loads(line)
        if last is None:
            return 0, GENESIS
        return last["seq"] + 1, last["hash"]

    def _record(self, kind: str, payload: dict) -> dict:
        body = {
            "seq": self._seq,
            "ts": _now(),
            "run_id": self.run_id,
            "actor": self.actor,
            "kind": kind,
            "payload": payload,
            "prev_hash": self._prev,
        }
        body["hash"] = _hash(self._prev, {k: v for k, v in body.items() if k != "hash"})
        with self.path.open("a") as fh:
            fh.write(_canonical(body) + "\n")
        self._prev = body["hash"]
        self._seq += 1
        return body

    @contextmanager
    def step(self, phase: str, inputs: dict | None = None) -> Iterator[Step]:
        """Record one decision. Writes on exit, including when the body raises —
        a crashed step is the most interesting kind and must not vanish."""
        s = Step(self, phase, inputs)
        try:
            yield s
        except Exception as exc:                      # noqa: BLE001 - deliberate
            s.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._record("step", {
                "phase": s.phase,
                "inputs": s.inputs,
                "observations": s.observations,
                "parameters": s.parameters,
                "rationale": s.rationale,
                "actions": s.actions,
                "outcome": s.outcome,
                "error": s.error,
                "duration_ms": round((time.perf_counter() - s._t0) * 1000, 2),
            })

    def note(self, message: str, **fields: Any) -> None:
        """A free-text entry for things that are not decisions — 'cache warm',
        'falling back to replay'. Still chained."""
        self._record("note", {"message": message, **redact(fields)})

    def close(self, **summary: Any) -> None:
        if self._closed:
            return
        self._record("run_end", redact(summary))
        self._closed = True


# --- verification -------------------------------------------------------------


def verify(path: Path | str = LOG_PATH) -> tuple[bool, str]:
    """Recompute every hash. Returns (ok, human-readable finding).

    Detects: an edited field, a deleted entry, a reordered entry, an entry spliced
    in. It does NOT detect someone recomputing the whole chain from scratch — that
    needs a signature or an external anchor, which is out of scope tonight and
    stated here so nobody oversells it.
    """
    path = Path(path)
    if not path.exists():
        return False, f"no audit trail at {path}"

    prev, count = GENESIS, 0
    with path.open() as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                return False, f"line {lineno}: not valid JSON ({exc})"

            if entry.get("prev_hash") != prev:
                return False, (f"seq {entry.get('seq')} (line {lineno}): prev_hash does "
                               f"not match the previous entry — an entry was removed, "
                               f"reordered, or inserted here")
            recomputed = _hash(prev, {k: v for k, v in entry.items() if k != "hash"})
            if recomputed != entry.get("hash"):
                return False, (f"seq {entry.get('seq')} (line {lineno}): contents were "
                               f"modified after it was written")
            if entry["seq"] != count:
                return False, f"line {lineno}: seq {entry['seq']}, expected {count}"
            prev = entry["hash"]
            count += 1

    return True, f"chain intact — {count} entries, head {prev[:12]}…"


def read(path: Path | str = LOG_PATH) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open() as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def export(path: Path | str = LOG_PATH, out: Path | str = EXPORT_PATH) -> dict:
    """Roll the chain up into a single JSON object the Next app can import.

    JSONL is the source of truth because appending cannot corrupt earlier lines;
    graph.ts imports `.json`, so it gets this.
    """
    entries = read(path)
    ok, finding = verify(path)
    doc = {
        "schema": SCHEMA_VERSION,
        "verified": ok,
        "finding": finding,
        "head": entries[-1]["hash"] if entries else GENESIS,
        "count": len(entries),
        "runs": sorted({e["run_id"] for e in entries}),
        "entries": entries,
    }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2))
    return doc


# --- self-test ----------------------------------------------------------------


def _selftest() -> int:
    import tempfile

    fails = 0
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "audit.jsonl"

        log = AuditLog(run_id="selftest", path=p)
        with log.step("assess", inputs={"node": "precursor:6-apa"}) as s:
            s.observe("cascade", {"affected": 787})
            s.params({"risk_weight": 0.7}, why="no public capacity data")
            s.action("rank_alternates", {"candidates": 8})
            s.result({"chosen": "company:name:example"})
        log.note("cache warm", entries=11)
        log.close(status="ok")

        ok, finding = verify(p)
        print(f"  {'OK  ' if ok else 'FAIL'} fresh chain verifies: {finding}")
        fails += not ok

        # A secret must never reach disk.
        log2 = AuditLog(run_id="secrets", path=p)
        log2.note("calling openFDA", api_key="SHOULD_NOT_APPEAR", url="https://api.fda.gov")
        log2.close()
        raw = p.read_text()
        leaked = "SHOULD_NOT_APPEAR" in raw
        print(f"  {'FAIL' if leaked else 'OK  '} credentials redacted before write")
        fails += leaked

        # A step that raises must still be recorded.
        log3 = AuditLog(run_id="crash", path=p)
        try:
            with log3.step("reroute") as s:
                s.params({"alpha": 1}, why="testing")
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        crashed = [e for e in read(p) if e["payload"].get("error")]
        print(f"  {'OK  ' if crashed else 'FAIL'} crashed step still recorded "
              f"({crashed[0]['payload']['error'] if crashed else 'MISSING'})")
        fails += not crashed

        # params() without a reason must be refused.
        refused = False
        try:
            with AuditLog(run_id="norationale", path=p).step("x") as s:
                s.params({"a": 1}, why="   ")
        except ValueError:
            refused = True
        print(f"  {'OK  ' if refused else 'FAIL'} params() without a rationale is refused")
        fails += not refused

        # Resuming must continue the chain, not fork it.
        before = len(read(p))
        AuditLog(run_id="resumed", path=p).close()
        ok, finding = verify(p)
        print(f"  {'OK  ' if ok else 'FAIL'} chain survives reopen "
              f"({before} -> {len(read(p))} entries)")
        fails += not ok

        clean = p.read_text().splitlines()   # snapshot: each tamper test starts here

        # THE POINT: edit one historical field and the chain must fail.
        lines = list(clean)
        victim = json.loads(lines[1])
        victim["payload"]["outcome"] = {"chosen": "somebody-else"}
        lines[1] = _canonical(victim)
        p.write_text("\n".join(lines) + "\n")
        ok, finding = verify(p)
        detected = not ok and "modified" in finding
        print(f"  {'OK  ' if detected else 'FAIL'} edit detected: {finding}")
        fails += not detected

        # A deletion from the middle breaks the prev_hash link, not the entry hash --
        # assert on the reason, or this test passes for the wrong reason.
        p.write_text("\n".join(l for i, l in enumerate(clean) if i != 2) + "\n")
        ok, finding = verify(p)
        detected = not ok and "removed, reordered, or inserted" in finding
        print(f"  {'OK  ' if detected else 'FAIL'} deletion detected: {finding}")
        fails += not detected

        # Reordering two entries must also fail.
        lines = list(clean)
        lines[1], lines[2] = lines[2], lines[1]
        p.write_text("\n".join(lines) + "\n")
        ok, _ = verify(p)
        print(f"  {'OK  ' if not ok else 'FAIL'} reordering detected")
        fails += ok

        # An untouched chain must still verify once restored.
        p.write_text("\n".join(clean) + "\n")
        ok, finding = verify(p)
        print(f"  {'OK  ' if ok else 'FAIL'} restored chain verifies again: {finding}")
        fails += not ok

    print("\nPASS — audit trail is tamper-evident" if not fails
          else f"\nFAIL — {fails} check(s) failed")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Tamper-evident agent audit trail")
    ap.add_argument("--verify", action="store_true", help="prove the chain is intact")
    ap.add_argument("--export", action="store_true", help="write web/data/audit.json")
    ap.add_argument("--tail", type=int, metavar="N", help="print the last N entries")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--path", default=str(LOG_PATH))
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    if args.verify:
        ok, finding = verify(args.path)
        print(("OK   " if ok else "FAIL ") + finding)
        return 0 if ok else 1

    if args.export:
        doc = export(args.path)
        print(f"wrote {EXPORT_PATH.relative_to(REPO_ROOT)} — {doc['count']} entries, "
              f"verified={doc['verified']}")
        return 0

    if args.tail:
        for e in read(args.path)[-args.tail:]:
            p = e["payload"]
            extra = f" {p.get('phase') or p.get('message') or ''}"
            print(f"  #{e['seq']:<4} {e['ts']}  {e['kind']:<9}{extra}")
            if p.get("rationale"):
                print(f"        why: {p['rationale']}")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
