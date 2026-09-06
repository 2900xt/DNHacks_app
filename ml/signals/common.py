"""Shared helpers for the Layer 1c signal loaders.

Every loader:
  * re-fetches from a public source (no key anywhere in this package),
  * PINS the raw response under `data/cache/<source>/` so the demo does not
    depend on venue wifi,
  * emits rows in the `web/data/signals.json` shape agreed in
    `team/briefs/README.md`, and
  * FAILS LOUDLY rather than writing an empty file. A zero-row result means the
    fetch broke, not that the world is calm.
"""

from __future__ import annotations

import json
import ssl
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "data" / "cache"
OUT = REPO / "web" / "data" / "signals.json"

# accessdata.fda.gov serves an "abuse detection" page to bare curl/urllib.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class LoaderError(RuntimeError):
    """Raised when a loader cannot produce data. Never swallowed."""


@dataclass
class Signal:
    """One row of `web/data/signals.json`."""

    node_id: str
    kind: str
    severity: str
    source: str
    observed_at: str          # ISO date
    url: str | None = None
    payload: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return asdict(self)


def cache_dir(name: str) -> Path:
    d = CACHE / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def ca_bundle() -> Path:
    """A PEM of the macOS system roots, exported once and cached.

    This python has no `certifi` and its framework install trusts nothing, so
    `urllib` fails TLS on every host here. Rather than modifying the user's
    Python (`Install Certificates.command`) or - much worse - disabling
    verification, we export the system keychain roots and verify against those.
    """
    pem = cache_dir("_ca") / "macos-roots.pem"
    if pem.exists() and pem.stat().st_size > 10_000:
        return pem
    out = subprocess.run(
        ["security", "find-certificate", "-a", "-p",
         "/System/Library/Keychains/SystemRootCertificates.keychain"],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0 or len(out.stdout) < 10_000:
        raise LoaderError("could not export macOS system roots for TLS verification")
    pem.write_text(out.stdout)
    return pem


def ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=str(ca_bundle()))


def fetch(url: str, dest: Path | None = None, *, timeout: int = 60, retries: int = 3) -> bytes:
    """GET with a browser UA, retries, and optional pinning to disk.

    Uses `curl` rather than `urllib`: curl verifies against the system trust
    store, which is the only one present on this machine, and it is what every
    command in the brain deep-dives was verified with.
    """
    last = ""
    for attempt in range(1, retries + 1):
        cmd = ["curl", "-sSL", "--fail", "-A", UA, "--max-time", str(timeout), url]
        if dest:
            cmd += ["-o", str(dest)]
        r = subprocess.run(cmd, capture_output=True, timeout=timeout + 30)
        if r.returncode == 0:
            return dest.read_bytes() if dest else r.stdout
        last = r.stderr.decode(errors="replace").strip()
        if attempt < retries:
            time.sleep(2 * attempt)
    raise LoaderError(f"GET failed after {retries} attempts: {url}\n  last error: {last}")


def iso(d: str, fmt: str) -> str:
    """Normalise a source date to ISO, or raise — never guess."""
    from datetime import datetime
    return datetime.strptime(d.strip(), fmt).date().isoformat()


def require(rows: list, source: str, minimum: int = 1) -> list:
    if len(rows) < minimum:
        raise LoaderError(
            f"{source}: got {len(rows)} rows, expected >= {minimum}. "
            "Refusing to write an empty signal set — a zero-row result means the "
            "fetch or the filter broke, not that there is nothing to report."
        )
    return rows


def write_signals(signals: list[Signal]) -> Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = [s.to_json() for s in signals]
    rows.sort(key=lambda r: (r["observed_at"], r["node_id"]), reverse=True)
    OUT.write_text(json.dumps(rows, indent=2) + "\n")
    return OUT
