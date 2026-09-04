# Example 6 — an external multi-agent application

Every other example in this folder evaluates something written for the arena.
This one points at a **separate codebase**: the Multi-Agent Research Assistant,
a four-agent LangGraph pipeline (planner → executor → critic → synthesizer)
that lives in its own repository and knows nothing about this one.

```bash
arena validate --project projects/mara     # imports the app, spends nothing
arena evaluate --project projects/mara     # offline, on the engine's fake provider
```

## What it compares

Not models — configurations. The three targets are the assistant's `fast`,
`balanced` and `comprehensive` depth settings: the choice you actually have to
make before shipping it, graded on whether the report comes back well-formed
and cited, and priced in money, wall-clock time, and critic rework loops.

## How the connection works

[`pipelines/mara.py`](pipelines/mara.py) is the whole contract — one `async def`
that takes a question and returns the report plus what the run really cost.
Three decisions in it are worth copying into your own adapter:

- **In-process, not over HTTP.** The assistant ships a local host (SQLite
  checkpointer, in-memory event sink), so the full pipeline runs with no Docker,
  Postgres, Redis or login. Fewer moving parts between the arena and the thing
  being measured.
- **A fresh temporary data directory per call.** A shared search cache would let
  an early test case subsidise a later one, which would quietly flatter whichever
  target ran second. Hermetic runs are the point of a fair comparison.
- **The engine's own cost numbers.** It counts four agents' spend; the price
  catalog sees one opaque call. When a target reports `cost_usd`, the arena
  believes it.

The adapter is `async` and is awaited directly — agent frameworks are
async-first, and no event-loop wrapper is needed.

## Where it looks for the app

The sibling checkout beside this repository, overridable:

```bash
MARA_BACKEND=/path/to/assistant/backend arena evaluate --project projects/mara
```

## Offline mode is honest about its limits

`fake: true` routes the engine at its scripted provider: no key, no spend, a
fixture report. That proves the wiring and the report's structure — it cannot
separate the three depths, because a fixture answer is the same answer at every
depth, and the leaderboard says exactly that instead of ranking noise.

Set `fake: false`, export the assistant's own provider keys (the arena never
sees them), and swap the structural cases in `tests.yaml` for substance ones
before trusting the order.
