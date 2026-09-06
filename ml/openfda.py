"""openFDA client with an on-disk cache.

Every response is written to ml/cache/ as JSON, keyed by a hash of the request.
Re-running ingest reads from disk and never touches the network. That is not a
nicety: the demo has to survive venue wifi being dead.

Usage:
    from ml.openfda import ndc, shortages, enforcement, drugsfda

    rows = ndc('generic_name:"amoxicillin"', limit=100)

Check your key works:
    python ml/openfda.py --check
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

# Load .env from the repo root (this file lives in ml/, so go up one level).
REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

API_KEY = os.getenv("OPENFDA_API_KEY", "").strip()
BASE_URL = "https://api.fda.gov"
CACHE_DIR = Path(__file__).resolve().parent / "cache"

# openFDA caps a single response at 1000 records.
MAX_LIMIT = 1000

# Be polite even with a key. openFDA allows 240 req/min with one.
MIN_SECONDS_BETWEEN_CALLS = 0.3
_last_call_at = 0.0


class OpenFDAError(RuntimeError):
    pass


def _cache_path(endpoint: str, params: dict[str, Any]) -> Path:
    """One file per unique request. The api_key is excluded from the hash so
    rotating the key does not invalidate the whole cache."""
    fingerprint = json.dumps([endpoint, params], sort_keys=True)
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()[:16]
    # Readable prefix so you can eyeball the cache dir: drug_ndc__a1b2c3d4.json
    slug = endpoint.strip("/").replace("/", "_").replace(".json", "")
    return CACHE_DIR / f"{slug}__{digest}.json"


def _throttle() -> None:
    global _last_call_at
    elapsed = time.monotonic() - _last_call_at
    if elapsed < MIN_SECONDS_BETWEEN_CALLS:
        time.sleep(MIN_SECONDS_BETWEEN_CALLS - elapsed)
    _last_call_at = time.monotonic()


def fetch(endpoint: str, params: dict[str, Any], *, refresh: bool = False) -> dict:
    """GET one page from openFDA, via the cache.

    Returns the raw response body. A search matching nothing comes back as
    {"results": []} rather than raising -- openFDA signals "no matches" with a
    404, which is not an error for our purposes.
    """
    cache_file = _cache_path(endpoint, params)

    if cache_file.exists() and not refresh:
        return json.loads(cache_file.read_text())

    query = dict(params)
    if API_KEY:
        query["api_key"] = API_KEY

    _throttle()
    response = requests.get(f"{BASE_URL}{endpoint}", params=query, timeout=30)

    if response.status_code == 404:
        body: dict = {"results": [], "meta": {"note": "no matches (openFDA 404)"}}
    elif response.status_code == 429:
        raise OpenFDAError(
            "Rate limited (429). Without a key the cap is 1,000 requests/day. "
            f"Key currently {'loaded' if API_KEY else 'MISSING -- check .env'}."
        )
    elif not response.ok:
        raise OpenFDAError(f"{response.status_code} from {endpoint}: {response.text[:300]}")
    else:
        body = response.json()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(body, indent=2))
    return body


def search(
    endpoint: str,
    query: str | None = None,
    *,
    limit: int = 100,
    max_records: int | None = None,
    refresh: bool = False,
) -> list[dict]:
    """Run a search and return the records, paging through with `skip` as needed.

    `limit` is the page size (max 1000). `max_records` caps the total pulled;
    None means "everything the query matches".
    """
    page_size = min(limit, MAX_LIMIT)
    collected: list[dict] = []
    skip = 0

    while True:
        params: dict[str, Any] = {"limit": page_size, "skip": skip}
        if query:
            params["search"] = query

        body = fetch(endpoint, params, refresh=refresh)
        page = body.get("results", [])
        collected.extend(page)

        total = body.get("meta", {}).get("results", {}).get("total", len(collected))
        skip += len(page)

        if not page or skip >= total:
            break
        if max_records is not None and len(collected) >= max_records:
            break

    return collected[:max_records] if max_records else collected


# --- the four endpoints -------------------------------------------------------
# Join across these on `application_number` and `product_ndc` inside the nested
# `openfda` block. Exact matching only -- fuzzy company matching is Parth's lane.


def ndc(query: str | None = None, **kwargs) -> list[dict]:
    """/drug/ndc.json -- the NDC directory. Marketed products, one row per NDC."""
    return search("/drug/ndc.json", query, **kwargs)


def shortages(query: str | None = None, **kwargs) -> list[dict]:
    """/drug/shortages.json -- FDA shortage records.

    Note for the backtest: only 7 of 1,634 rows are `Resolved` (resolved records
    get purged), so you cannot get durations from this. `initial_posting_date` is
    populated on all 1,634, spanning 2012-01-01 to 2026-09-01. Score ONSET.

    Dates must be dashed: initial_posting_date:[2023-01-01+TO+2026-09-05].
    The compact 20230101 form returns NOT_FOUND.
    """
    return search("/drug/shortages.json", query, **kwargs)


def enforcement(query: str | None = None, **kwargs) -> list[dict]:
    """/drug/enforcement.json -- recalls and enforcement reports."""
    return search("/drug/enforcement.json", query, **kwargs)


def drugsfda(query: str | None = None, **kwargs) -> list[dict]:
    """/drug/drugsfda.json -- approvals, keyed by application_number."""
    return search("/drug/drugsfda.json", query, **kwargs)


# --- key check ----------------------------------------------------------------


def _check() -> int:
    if not API_KEY:
        print("FAIL  OPENFDA_API_KEY is empty.")
        print(f"      Edit {REPO_ROOT / '.env'} and set OPENFDA_API_KEY=<your key>")
        return 1
    if API_KEY == "PASTE_YOUR_KEY_HERE":
        print("FAIL  OPENFDA_API_KEY is still the placeholder.")
        print(f"      Edit {REPO_ROOT / '.env'} and paste your real key.")
        return 1

    print(f"key    loaded ({len(API_KEY)} chars, ends ...{API_KEY[-4:]})")

    rows = ndc('generic_name:"amoxicillin"', limit=1, max_records=1, refresh=True)
    if not rows:
        print("FAIL  key loaded but the test query returned nothing.")
        return 1

    row = rows[0]
    print(f"query  OK -- 1 amoxicillin NDC returned")
    print(f"       product_ndc  {row.get('product_ndc')}")
    print(f"       labeler      {row.get('labeler_name')}")
    print(f"cache  {CACHE_DIR}")
    print("\nPASS   openFDA client is working.")
    return 0


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(_check())
    print(__doc__)
