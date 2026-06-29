# Architecture Decision Records (ADRs)

The following ADRs document the core design choices made during the development of Agent Arena. 

| ADR | Title | Decision Summary |
|---|---|---|
| [ADR 0001](adr/0001-trace-format.md) | Trace Format | Enforce a unified, append-only JSONL trace schema across all architectures to enable robust, standardized evaluation. |
| [ADR 0002](adr/0002-baseline-fairness.md) | Baseline Fairness | Ensure the single-agent baseline has unrestricted tool access so multi-agent boundary failures cannot be dismissed as a rigged baseline. |
| [ADR 0003](adr/0003-failure-taxonomy.md) | Failure Taxonomy | Classify failures cleanly into `task_failure`, `coordination_failure`, `tool_error_unrecovered`, or `incomplete`. |
| [ADR 0004](adr/0004-retry-strategy.md) | Retry Strategy | Use a two-layer strategy: deterministic infrastructure retries via `tenacity` (e.g. 429s) and semantic LLM retries (e.g. invalid arguments). |
| [ADR 0008](adr/0008-supervisor-worker-architecture.md) | Supervisor-Worker | Implement a hierarchical pattern where a supervisor delegates sub-tasks to specialized workers, receiving natural-language summaries back. |
| [ADR 0005](adr/0005-tool-failure-injection.md) | Tool Failure Injection | Inject deterministic mock API failures to stress test an agent's retry loop. |
| [ADR 0006](adr/0006-model-agnostic-provider.md) | Model-Agnostic Provider | Abstract LLM API calls behind a unified interface to test both Anthropic and Gemini seamlessly. |
| [ADR 0009](adr/0009-peer-to-peer-architecture.md) | Peer-to-Peer | Implement independent agents coordinating via a rigid JSON handoff message. |
| [ADR 0010](adr/0010-debate-critic-architecture.md) | Debate-Critic | Implement a proposer-critic model where a critic forces revisions if it detects logical flaws. |

> **Note:** ADR 0007 is intentionally skipped. The number was retired during the 2026-06 renumbering cleanup when a collision was resolved — the file formerly named `0007-debate-critic-architecture.md` was reassigned to ADR 0010. No file is missing.
