# services/api/

Backend: ingest, orchestration, and the surface the UI talks to.

**Stack:** _TBD_ — FastAPI, Express/Hono, or Axum. Pick whatever the owner can write
without looking anything up.

## Contract

Implements [`../../contracts/openapi.yaml`](../../contracts/openapi.yaml).

## Non-negotiables

- `GET /health` works from the first commit.
- **CORS wide open** in dev. This costs 30 seconds now and an hour at 2am.
- Everything in memory is fine. Do not add a database unless the demo needs
  history to survive a restart.
- `GET /stream` (SSE) beats polling — a screen that updates by itself is a
  significantly better demo than one with a refresh button.

## Notes

_Run command:_
_Port:_
