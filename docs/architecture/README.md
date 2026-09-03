# Architecture

How Agent Arena is put together, and why.

## The shape of it

```text
   arena CLI              web/api.py              import agent_arena
   (argparse)             (http.server)           (library use)
        │                      │                        │
        └──────────────────────┼────────────────────────┘
                               ▼
                     agent_arena/service/
        secrets · settings · projects · runs · providers · export
                               │
   ┌──────────┬──────────┬─────┴──────┬─────────────┬────────────┐
   ▼          ▼          ▼            ▼             ▼            ▼
 config     runner    metrics       store      connectors    scorers
                    (agent_arena/core/, agent_arena/connectors/, …)
```

The dependency arrow points one way. `service/` may import from `core/`,
`connectors/` and `scorers/`; it may never import from `web/`. That is
invariant 7 in [../../AGENTS.md](../../AGENTS.md), and it exists because before
the service layer, project creation lived inside `web/api.py` where the CLI
could not reach it — so the UI could scaffold a project the CLI could not, and
neither could delete one.

## What each package owns

| Package | Owns |
|---|---|
| `agent_arena/core/` | Config parsing, the run loop, metrics and the leaderboard, SQLite storage, report rendering, test-case loading, hooks, retry policy |
| `agent_arena/connectors/` | The uniform model interface and its six implementations, provider inference, the price book |
| `agent_arena/scorers/` | The `Scorer` contract and the ten builtin eval types |
| `agent_arena/service/` | Use cases shared by every interface |
| `agent_arena/web/` | `http.server` routing, the JSON API, the plain-English layer, and the vanilla-JS front end |
| `agent_arena/cli.py` | Argument parsing and terminal output |

## Pages

| Page | What it answers |
|---|---|
| [system-design.md](system-design.md) | Why the system is shaped this way, and what happens end to end during a run |
| [data-model.md](data-model.md) | The SQLite schema and the config schema, field by field |
| [runner.md](runner.md) | Concurrency, trials, timeouts, retries, and the abort path |
| [scoring.md](scoring.md) | The scorer contract, the ten builtins, custom scorers, hooks |
| [metrics.md](metrics.md) | How a leaderboard is built, normalized, weighted and gated |
| [connectors.md](connectors.md) | The model interface, provider inference, and pricing |
