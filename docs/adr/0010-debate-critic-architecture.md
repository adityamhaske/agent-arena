# ADR 0010: Debate-Critic Architecture

**Date:** 2026-06-27
**Status:** Accepted

## Context
We want to test whether a self-review cycle (a proposer generating a draft and a separate critic reviewing it) improves task accuracy versus a single-pass agent. The key behavioral question is: does structured self-critique catch and correct errors that the proposer would not recover from on its own?

## Decision
Implement a `DebateCriticArchitecture` with three phases:

1. **Phase 1 — Proposer**: a full agent with all tools attempts the task and produces a draft answer.
2. **Phase 2 — Critic**: a tool-free agent receives (task + draft answer + tool call log) and produces a structured critique. If no issues are found, it outputs `LGTM: no issues found.`
3. **Phase 3 — Revision**: the proposer receives (task + its own draft + critic's critique) and performs any corrective tool calls before producing the final answer.

The critic reads the tool call log from the trace file directly using `TraceLogger.reconstruct_dag()`, making the critique grounded in actual execution evidence, not just the proposer's self-reported output.

## Trace Events
Adds: `critic_review` (contains draft, tool_summary, critique), `revision_start`, `revision_finish`, `run_finish`.

## Consequences
- **Positive:** The critic introduces a second reasoning perspective. It can catch wrong field values, missed steps, or unresolved errors that the proposer glossed over in its final summary.
- **Negative:** Approximately 3× the token cost and latency of a single-agent run (proposer + critic + revision). The critic is the same model family as the proposer, limiting how different its perspective is. Critic quality degrades if it cannot access tool results (tool call log must be accurately extracted).
