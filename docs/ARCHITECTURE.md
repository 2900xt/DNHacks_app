# Architecture

> Fill this in the moment the idea is locked. An empty architecture doc at hour 6
> means two people are about to build the same thing.

## One-sentence description

_TBD — what the system does, in the words you'd use on stage._

## Stack decisions

| Component | Stack | Chosen because | Decided at |
|-----------|-------|----------------|------------|
| `firmware/` | TBD | | |
| `ml/` | TBD | | |
| `services/api/` | TBD | | |
| `web/` | TBD | | |

## Data flow

```
[ device ] --telemetry--> [ services/api ] --window--> [ ml ]
                                 |                       |
                                 |<------detection-------+
                                 v
                            [ web UI ]
```

Every arrow above is a contract in [`../contracts/`](../contracts/). If you draw a
new arrow, write the schema first.

## Deliberate non-goals

Things we are consciously NOT building. Add to this list aggressively — it is how
you protect the demo.

- Auth / user accounts
- Persistence beyond the demo session
- Multi-tenant anything
- Mobile support

## Known fragility

_What will break during the demo, and the fallback for each._

| Risk | Likelihood | Fallback |
|------|-----------|----------|
| Venue wifi drops | High | Everything runs on localhost / a phone hotspot |
| Hardware doesn't enumerate | Medium | Recorded telemetry replay (`scripts/replay.sh`) |
| Model too slow live | Medium | Pre-computed results for the demo scenario |
