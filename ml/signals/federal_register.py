"""Federal Register — regulatory disruption signals.

Free, no auth, no rate limit observed. Publishes business days only, so the feed
is frozen across the judging weekend — read from the pinned cache on stage.

❗ Attaches to COMPANY and COUNTRY nodes only. Drug-name matching against this
source is ~60% noise (the top "penicillin" hit is a Medicare payment rule listing
it in a reimbursement table), so we never emit a drug-node signal from here.
"""

from __future__ import annotations

import json
import urllib.parse

from .common import Signal, cache_dir, fetch, iso, require

BASE = "https://www.federalregister.gov/api/v1/documents.json"

#: Queries pinned because they were live-verified to return real, on-topic hits.
QUERIES = [
    {"key": "s232-pharma", "params": {
        "conditions[term]": '"pharmaceuticals and pharmaceutical ingredients"',
        "conditions[publication_date][gte]": "2025-01-01", "per_page": "20"}},
    {"key": "dod-1260h", "params": {
        "conditions[docket_id]": "DOD-2026-OS-1288", "per_page": "20"}},
    {"key": "bis-actions", "params": {
        "conditions[agencies][]": "industry-and-security-bureau",
        "conditions[term]": "pharmaceutical", "per_page": "20"}},
]

FIELDS = ["document_number", "title", "type", "abstract", "publication_date",
          "html_url", "agencies", "docket_ids", "citation", "raw_text_url"]

#: Company nodes this feed can legitimately fire on. NCPC and CSPC are absent
#: from this source entirely (count: 0) - verified, and deliberately not faked.
COMPANIES = {
    "wuxi apptec": "company:name:wuxi-apptec",
    "bgi group": "company:name:bgi-group",
    "bgi genomics": "company:name:bgi-genomics",
    "mgi tech": "company:name:mgi-tech",
    "complete genomics": "company:name:complete-genomics",
    "origincell": "company:name:origincell",
    "novogene": "company:name:novogene",
}
COUNTRIES = {"china": "country:cn", "chinese": "country:cn", "india": "country:in", "indian": "country:in"}


def _severity(doc: dict) -> str:
    t = (doc.get("type") or "").lower()
    if t in {"presidential document", "rule"}:
        return "high"
    return "medium" if t == "proposed rule" else "low"


def _full_text(doc: dict, cache) -> str:
    """Fetch and pin the document body. Returns '' if the source has none."""
    url = doc.get("raw_text_url")
    if not url:
        return ""
    dest = cache / f"text-{doc['document_number']}.txt"
    if dest.exists():
        return dest.read_text(errors="replace")
    try:
        return fetch(url, dest, timeout=45).decode(errors="replace")
    except Exception:
        return ""   # a missing body must not kill the whole loader


def load() -> list[Signal]:
    cache = cache_dir("federal-register")
    seen: set[tuple[str, str]] = set()
    out: list[Signal] = []

    for q in QUERIES:
        params = list(q["params"].items()) + [("fields[]", f) for f in FIELDS]
        url = f"{BASE}?{urllib.parse.urlencode(params)}"
        body = fetch(url, cache / f"{q['key']}.json")
        docs = json.loads(body).get("results") or []

        for doc in docs:
            hay = " ".join(str(doc.get(k) or "") for k in ("title", "abstract")).lower()
            # Company names appear in the BODY, not the title - the 1260H notice
            # names WuXi AppTec and BGI Group only in its full text. Country
            # matching works on the summary; company matching needs this.
            body_text = _full_text(doc, cache)
            hay_full = hay + " " + body_text.lower()
            targets = {node for name, node in COMPANIES.items() if name in hay_full}
            targets |= {node for name, node in COUNTRIES.items() if name in hay}
            if not targets:
                continue
            for node in targets:
                key = (node, doc["document_number"])
                if key in seen:
                    continue
                seen.add(key)
                out.append(Signal(
                    node_id=node,
                    kind="regulatory_action",
                    severity=_severity(doc),
                    source="Federal Register",
                    observed_at=iso(doc["publication_date"], "%Y-%m-%d"),
                    url=doc.get("html_url"),
                    payload={"document_number": doc["document_number"],
                             "title": doc.get("title"), "type": doc.get("type"),
                             "citation": doc.get("citation"), "query": q["key"],
                             "matched_in": "full_text" if node.startswith("company:") else "summary"},
                ))

    return require(out, "federal_register")


if __name__ == "__main__":
    for s in load():
        print(f"{s.observed_at}  {s.node_id:34s} {s.severity:6s} {(s.payload.get('title') or '')[:70]}")
