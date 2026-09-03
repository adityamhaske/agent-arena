# ADR 0003: Failure Taxonomy

**Date:** 2026-06-22  
**Status:** Accepted  

## Context
When comparing complex architectures, pass/fail grading is insufficient. We need to distinguish between a model being "dumb" (making a bad logical decision), an architecture being lossy (dropping critical data during a handoff), and infrastructure being flaky (hitting a rate limit). Without a strict taxonomy, these distinct failure modes blur together into meaningless "fail" states.

## Decision
We implemented a strict failure classification system in `evals/grader.py`. All failures must fall into one of these four categories:

1. **`task_failure`**: The agent had access to all necessary data but failed to execute the logic correctly (e.g., hallucinated a tool call that never fired, or deliberately ignored a policy despite seeing the data).
2. **`coordination_failure`**: The architectural machinery either never activated, or critical information was definitively dropped at an architectural boundary (e.g., omitted from a handoff schema or a natural-language summary), denying the decision-maker the data it needed.
3. **`tool_error_unrecovered`**: The agent encountered an injected tool failure (e.g., 500 error) and failed to trigger its semantic retry loop to recover.
4. **`incomplete`**: The run crashed or hit a quota limit (e.g., 429) before a finish event was emitted.

## Consequences
This granular taxonomy allowed for clean interpretation of the Phase 4 sweep results. For instance, when `peer_to_peer` dropped the `credit_hold` flag due to its rigid schema, the grader correctly classified it as a `coordination_failure`. Conversely, when `supervisor_worker` hallucinated a successful tool call on `task_01`, it was accurately classified as a `task_failure` (a general LLM reliability issue), rather than conflated with architectural data loss.
