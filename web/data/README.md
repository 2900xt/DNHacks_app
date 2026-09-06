# web/data/ — the graph artifacts

There is no database ([decision 0004](../../../DNHacks_brain/decisions/0004-no-database-json-artifacts.md)).
Loaders in `ml/` write JSON here, it is committed to git, and the app imports it and
traverses in memory. It lives under `web/` so Vercel bundles it — no runtime paths, no
env vars.

## One file per producer — never write to a file you do not own

| File | Owner | Shape |
|---|---|---|
| `nodes.openfda.json` | Nikhil | `[{ id, type, label, country, critical, attrs, resolved_by }]` |
| `edges.openfda.json` | Nikhil | `[{ src, dst, rel, layer, citation }]` |
| `nodes.curated.json` | **Yash** | same as nodes — Layer 2 + 3 |
| `edges.curated.json` | **Yash** | same as edges — Layer 2 + 3 |
| `compliance.json` | **Yash** | `[{ node_id, taa_pass, on_1260h, evidence }]` |
| `signals.json` | Parth | `[{ node_id, kind, severity, source, observed_at, url, payload }]` |
| `bins.json` | Taha | `[{ id, label, covers_drugs }]` |
| `backtest.json` | Nikhil | `{ run_at, cutoff, params, result }` |

Nodes and edges from different producers are merged by the app, not by you. `telemetry`
has no file — it is live, in-memory, streamed over SSE.

## Validate before you push

```sh
python3 ml/load/validate.py
```

Exits non-zero on any contract violation. It enforces:

1. **Node ids follow `type:key`** — lowercase, ASCII, hyphen-separated. FEI wins.
2. **`company:name:` ids must set `resolved_by: "fuzzy"`** so the UI can mark them.
3. **`edges.layer` is 1 (live API), 2 (official list) or 3 (curated).**
4. **Layer 3 requires a non-empty `citation`. No citation, no edge.**
5. **`compliance.evidence` must be non-empty** — every PASS/FAIL carries its source
   ([decision 0003](../../../DNHacks_brain/decisions/0003-transparent-risk-rules.md)).
6. **`bins.covers_drugs` holds `drug:` ids**, e.g. `["drug:amoxicillin"]`, not bare names.

Unresolved cross-file references are **warnings, not errors** — lanes land at different
times, so an edge into a node nobody has written yet is expected until everyone has run.

## Provenance of the current rows

These are real rows from the Layer 2 sources, not placeholders — enough to pin every
field and exercise every rule. The full loads land in `ml/load/load_*.py`.

| Vintage | Source |
|---|---|
| Oct 30 2020 | FDA EO 13944 essential medicines |
| static | TAA designated countries, FAR 25.003 |
| Jun 10 2026 | DoD 1260H, 91 FR 35189 |
| 2Q2026 | FDA Type II DMF register |
| Sep 4 2026 | FDA DECRS |
