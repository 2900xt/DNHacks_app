# CLAUDE.md — DNHacks_app (application repo)

## What this is

The DNHacks 2026 project. Polyglot monorepo: embedded firmware, ML, a backend
service, and a web UI. Built under a hard deadline (submissions **noon Sunday,
Sept 6 2026**).

## Sibling brain repo

Strategy, demo path, team assignments, and decision history live in the **brain**
repo at `../DNHacks_brain`. It is a separate git repo, checked out as a sibling:

```
DNHacks26/
├── DNHacks_app/    <- you are here
└── DNHacks_brain/  <- strategy, agents, team coordination
```

Before making a non-trivial decision, read `../DNHacks_brain/status/STATUS.md` and
`../DNHacks_brain/strategy/DEMO_PATH.md`. If those files disagree with the code,
the demo path wins — say so and flag it.

## Working rules under hackathon time pressure

1. **The demo path is the spec.** Anything not on the demo path in
   `../DNHacks_brain/strategy/DEMO_PATH.md` is a nice-to-have. Do not build it
   until the must-haves work end to end.
2. **Simplify, don't stall.** If something is blocked for more than ~30 minutes,
   propose a degraded version that still demos, and say what was given up.
   Never leave the build broken while chasing the ideal version.
3. **Contracts before code.** Cross-component data shapes live in `contracts/`.
   Change the contract file in the same commit as the code that depends on it.
4. **Lean on libraries.** Judges cannot tell what was written versus imported.
   Prefer a dependency over hand-rolled logic, every time.
5. **Never leave `main` un-runnable.** Someone will pull it at 3am.

## Conventions

- Secrets go in `.env` (gitignored). Add every new key to `.env.example`.
- Each component owns its own toolchain; do not add a root-level package manager
  unless the team agrees. Wire new components into the root `Makefile` instead.
- Commit messages: `<component>: <what changed>` — e.g. `firmware: add IMU sampling`.

## Do not

- Do not refactor for elegance. There is no "later" here.
- Do not add CI, linting gates, or pre-commit hooks that can block a push.
- Do not rename or restructure directories without updating the brain repo's
  `context/REPO_MAP.md`.
