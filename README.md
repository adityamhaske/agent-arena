# Agent Arena

A config-driven harness for answering one question for *your* project: **which
model should we use, and what does that choice cost us?**

The engine knows nothing about any project. A project is a folder containing a
config file and some test cases; point the arena at it and it runs every model
against every case, scores the outputs with pluggable scorers, and ranks the
field by a weighted composite of the criteria you said mattered.

```bash
pip install -e .
arena evaluate --project projects/support_triage   # runs offline, no API key needed
arena evaluate --project projects/local_demo       # your local models (Ollama etc.)
arena init projects/my_project                     # then point it at your own work
```

You get a console leaderboard, a Markdown report, a JSON dump, and a SQLite
database you can query across runs.

**Start here:** the **[end-to-end demo](demo.md)** — a full walkthrough using
models running on your own machine — or the
**[Universal Arena guide](docs/UNIVERSAL_ARENA.md)**.

## Why it works this way

- **The engine is stdlib-only.** PyYAML is the single dependency, and even that
  is optional — JSON config and test files work without it. Every provider SDK
  imports lazily, so you install only what you actually call.
- **One code path.** To evaluate a different project, copy the template, change
  the test cases and the weights, and run the same command.
- **Small margins are called out.** When the top two models are within 0.02, the
  report says so and suggests more trials — a leaderboard implies more precision
  than a 12-case sweep can support.
- **The mock provider is deterministic** per `(model, test, trial)`, so demo
  runs, tests, and CI are reproducible.

## Documentation

- **[Demo](demo.md)** — end-to-end walkthrough with local models, system design diagrams, real output
- **[Universal Arena guide](docs/UNIVERSAL_ARENA.md)** — the full reference, plus a [sample report](docs/EXAMPLE_REPORT.md)
- **[Decisions (ADRs)](docs/DECISIONS.md)** — the rationale behind trace formats, retry strategies, tool failure injection, and the config-driven design

---

## Also in this repo: the multi-agent handoff study

Before the arena, this repo held a study asking the opposite question. The two
share a philosophy — structured evidence over vibes — but no code.

| | Question it answers | What varies | What is held fixed |
|---|---|---|---|
| **Universal arena** (this README) | Which model should *my* project use, on *my* criteria? | The model | The task |
| **[Multi-agent study](studies/multi_agent_handoff/)** | Does splitting a task across agents lose information at the handoff? | The architecture | The model, the task |

The study is **complete and frozen**, and is not part of the installable
package. Its finding: multi-agent decomposition can silently drop information at
coordination boundaries, independent of model capability. On an information
asymmetry trap task, `peer_to_peer` failed 100% of the time (0/5 trials) due to
a rigid handoff schema; `supervisor_worker` failed probabilistically (29%)
depending on whether an intermediate agent's natural-language summary happened
to mention the relevant field.

→ Full report: [studies/multi_agent_handoff/results/sweep_20260627/report.md](studies/multi_agent_handoff/results/sweep_20260627/report.md)
