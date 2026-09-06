# contracts/

**The source of truth for every data shape that crosses a component boundary.**

This directory exists because the single most common way a hackathon demo dies is
two people building against different assumptions about the same JSON.

## Rules

1. If data moves between `hardware/`, `ml/`, `services/api/`, or `web/`, its shape
   is defined **here** — not in a component.
2. Change the contract **before** the code that depends on it.
3. Announce every contract change in the team channel *and* run
   `/contract` in the brain repo so the change lands in the decision log.
4. Additive changes (new optional field) are free. Renames and type changes are
   not — they need a heads-up to whoever consumes the field.

## Files

| File | What it defines |
|------|-----------------|
| `openapi.yaml` | HTTP surface of `services/api` |
| `schemas/telemetry.schema.json` | What a device emits upstream |
| `schemas/detection.schema.json` | What the model emits, and what the UI renders |

## These are placeholders

The shapes below model a generic **sense → ingest → infer → display** pipeline,
which is the common spine for a hardware + ML + dashboard project. They are here so
work can start in parallel on day zero. **Replace them with the real shapes as soon
as the idea is locked** — do not contort the project to fit the placeholder.

## CHOKEPOINT graph types

- **[`types.ts`](types.ts)** — graph, signal, compliance, bin and backtest shapes.
  Mirrored from `../web/app/lib/types.ts`. The JSON artifacts they describe live in
  [`../web/data/`](../web/data/), one file per producer.
  **There is no database** — `../../DNHacks_brain/decisions/0004-no-database-json-artifacts.md`.

## Who serves what

Two backends, deliberately, and they do not overlap:

| Concern | Owner | Where |
|---|---|---|
| Hardware · depot · telemetry · SSE | **Taha** | Python, `../services/api/` — `/telemetry`, `/depot/*`, `/depot/stream` |
| Graph · cascade · signals · backtest | **Shaurya** | Next.js routes, `../web/app/api/*` |

`depot.schema.json` is Taha's live contract for the first row — `web/app/lib/depot.ts`
mirrors it. Do not delete it.
