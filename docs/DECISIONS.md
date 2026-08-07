# Architecture Decision Records (ADRs)

The following ADRs document the core design choices made during the development of Agent Arena.

This is a single repo-wide log covering both systems in the repo, kept as one
numbered sequence so the history and its cross-references stay intact. The
**System** column says which codebase each decision governs:

- **Study** — the frozen multi-agent handoff study at [`studies/multi_agent_handoff/`](../studies/multi_agent_handoff/)
- **Arena** — the universal config-driven arena at `agent_arena/` (see [UNIVERSAL_ARENA.md](UNIVERSAL_ARENA.md))

> **On paths in Study ADRs.** These records are kept as written at the time each
> decision was made, so they refer to `core/`, `evals/`, `run_all.py` and
> `results/` as top-level paths. Those files now live under
> `studies/multi_agent_handoff/`; read the paths as relative to that directory.
> The decisions themselves are unchanged.

| ADR | System | Title | Decision Summary |
|---|---|---|---|
| [ADR 0001](adr/0001-trace-format.md) | Study | Trace Format | Enforce a unified, append-only JSONL trace schema across all architectures to enable robust, standardized evaluation. |
| [ADR 0002](adr/0002-baseline-fairness.md) | Study | Baseline Fairness | Ensure the single-agent baseline has unrestricted tool access so multi-agent boundary failures cannot be dismissed as a rigged baseline. |
| [ADR 0003](adr/0003-failure-taxonomy.md) | Study | Failure Taxonomy | Classify failures cleanly into `task_failure`, `coordination_failure`, `tool_error_unrecovered`, or `incomplete`. |
| [ADR 0004](adr/0004-retry-strategy.md) | Study | Retry Strategy | Use a two-layer strategy: deterministic infrastructure retries via `tenacity` (e.g. 429s) and semantic LLM retries (e.g. invalid arguments). |
| [ADR 0008](adr/0008-supervisor-worker-architecture.md) | Study | Supervisor-Worker | Implement a hierarchical pattern where a supervisor delegates sub-tasks to specialized workers, receiving natural-language summaries back. |
| [ADR 0005](adr/0005-tool-failure-injection.md) | Study | Tool Failure Injection | Inject deterministic mock API failures to stress test an agent's retry loop. |
| [ADR 0006](adr/0006-model-agnostic-provider.md) | Study | Model-Agnostic Provider | Abstract LLM API calls behind a unified interface to test both Anthropic and Gemini seamlessly. |
| [ADR 0009](adr/0009-peer-to-peer-architecture.md) | Study | Peer-to-Peer | Implement independent agents coordinating via a rigid JSON handoff message. |
| [ADR 0010](adr/0010-debate-critic-architecture.md) | Study | Debate-Critic | Implement a proposer-critic model where a critic forces revisions if it detects logical flaws. |
| [ADR 0011](adr/0011-universal-config-driven-arena.md) | Arena | Universal Config-Driven Arena | Add a second, additive engine (`agent_arena/`) that varies the *model* and holds the task fixed, driven entirely by a per-project config folder. |

> **Note:** ADR 0007 is intentionally skipped. The number was retired during the 2026-06 renumbering cleanup when a collision was resolved — the file formerly named `0007-debate-critic-architecture.md` was reassigned to ADR 0010. No file is missing.
