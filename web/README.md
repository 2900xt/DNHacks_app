# web/

Depot viewer. Plain read-only page over `services/api` — no styling work done here
on purpose.

**Stack:** Next.js 16 (App Router) + TypeScript. Decided Sat evening.

```
npm run dev     # http://localhost:3000   (also started by `make dev`)
```

## What it shows

One bin at a time — the first that has reported — plus a table of all bins.

- Latest reading, every field the device sends
- The evaluation: **arithmetic mean beside MKT**, against the ceiling. That
  contrast is the point of the page; the mean reads in band while the MKT
  condemns the stock.
- Downstream drug list from `covers_drugs`
- History point count and span

## Contract

Types in [`app/lib/depot.ts`](app/lib/depot.ts) mirror
[`../contracts/schemas/depot.schema.json`](../contracts/schemas/depot.schema.json).
Change both in the same commit. The page must never invent a field.

Data comes in over `GET /depot/stream` (SSE, one node per event, fires only on
state change) seeded by `GET /depot/nodes`, with `GET /depot/nodes/{id}/history`
for the trace so a refresh mid-demo repaints instead of starting blank.

`NEXT_PUBLIC_API_BASE` overrides the API origin; defaults to `http://localhost:8000`.

## Not built

The sourcing graph. Nothing here renders 6-APA → producers → drugs — the page
only fans out to the bare drug names in `covers_drugs`. That half still has no
owner.
