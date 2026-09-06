# web/data — the shared data contract

**No database.** See `../../../DNHacks_brain/decisions/0004-no-database-json-artifacts.md`.

Loaders in `../../ml/` write these files. The app imports and merges them in
`../src/lib/graph.ts`. They live under `web/` so Vercel bundles them automatically —
no runtime file paths, no env vars.

## One file per producer — never write to a file you do not own

| File | Owner |
|---|---|
| `nodes.openfda.json` · `edges.openfda.json` | Nikhil |
| `nodes.curated.json` · `edges.curated.json` · `compliance.json` | Yash |
| `signals.json` | Parth |
| `bins.json` | Taha |
| `backtest.json` | Nikhil |
| `reroute.json` | Parth — `ml/aegis.py --write`. Every DMF holder per precursor, scored; the console re-ranks survivors itself |

Nodes and edges from different producers are merged by the app, not by you.

## Rules

1. `edges.layer` — **1 = live API, 2 = official list, 3 = curated.** Not decoration; it
   is how we say which layer is which on stage.
2. **Layer 3 requires a non-empty `citation`. No citation, no edge.**
3. `resolved_by` is `'fei' | 'duns' | 'fuzzy'`. Any `company:name:` id **must** be `'fuzzy'`.
4. `covers_drugs` holds `drug:` ids, e.g. `["drug:amoxicillin"]`.
5. **Telemetry has no file** — it is in-memory in the API and streams over SSE.

Shapes are in `../src/lib/types.ts`, mirrored to `../../contracts/`.
