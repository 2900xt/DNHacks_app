# web/

Operator UI. **This is the thing judges actually look at.**

**Stack:** _TBD_ — Next.js, Vite + React, or SvelteKit. Pick the one the owner has
shipped before.

## Contract

Consumes [`../contracts/openapi.yaml`](../contracts/openapi.yaml). It reads
`Detection` objects and renders them. It must never invent fields.

## This component is graded hardest

The judge forms an opinion in the first ~10 seconds, before you say anything.
High-value, cheap visuals:

- **A map** with live markers (Mapbox / MapLibre / Leaflet)
- **A live-updating feed** — motion signals "this is running right now"
- **Evidence inline** — the image/clip that triggered the detection, not a link to it
- **Severity colour** that changes on screen during the demo

Use a component library (shadcn/ui, Mantine). Nobody gets points for hand-written CSS.

## Notes

_Run command:_
_Dev URL:_
