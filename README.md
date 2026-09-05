# dnhacks26

Project repository for **DNHacks 2026** (Sept 5–6, 2026 · Station DC · Defense track).

Polyglot monorepo. Each top-level directory is an independently ownable component
with a defined boundary, so several people (and several Claude Code sessions) can
work in parallel without colliding.

| Path            | Component                        | Owner | Stack |
|-----------------|----------------------------------|-------|-------|
| `firmware/`     | Embedded / sensor / device       | TBD   | TBD   |
| `ml/`           | Models, training, inference      | TBD   | TBD   |
| `services/api/` | Backend, ingest, orchestration   | TBD   | TBD   |
| `web/`          | Operator UI / dashboard / demo   | TBD   | TBD   |
| `contracts/`    | **Shared API contracts** (source of truth) | everyone | JSON Schema + OpenAPI |

> Stacks are deliberately unfilled. Pick them once the idea is locked, then record
> the choice in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and in the brain repo's
> decision log.

## The one rule

**`contracts/` is decided before parallel work starts, and changes to it are announced.**

Judges never see this repo — but a contract mismatch at hour 20 is what kills demos.
If you need a field that doesn't exist, change the contract *first*, then tell the team.

## Quick start

```bash
make help          # see what's wired up
./scripts/bootstrap.sh   # install deps for whichever components exist
make dev           # run everything that has a dev target
```

## Related

The **brain** repo (`../dnhacks26-brain`) holds strategy, demo path, team assignments,
and the Claude Code agents that coordinate this build. Start there when you're lost.
