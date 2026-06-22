# ADR 0001: Trace Format

**Date:** 2026-06-22
**Status:** Accepted

## Context
Agent Arena needs a structured way to evaluate and compare different agent architectures (single-agent, supervisor-worker, etc.). A shared, structured trace format is required to reconstruct the execution sequence (DAG), analyze failure points, and measure performance deterministically.

## Decision
We will use a JSON Lines (JSONL) based `TraceEvent` schema. Each line in the trace file represents a single event.

The `TraceEvent` will contain the following fields:
- `event_id` (String/UUID): Unique identifier for the event.
- `parent_event_id` (String/UUID, optional): Identifier of the parent event, allowing reconstruction of execution DAGs (e.g., a tool call's parent is the LLM call that initiated it).
- `timestamp` (String/ISO8601): When the event occurred.
- `event_type` (String): Categorical type of the event (e.g., `run_start`, `agent_step`, `llm_call`, `tool_call`, `tool_result`, `error`).
- `payload` (Dictionary): The event-specific payload (e.g., LLM prompts, tool arguments, tool outputs, error traces).
- `metadata` (Dictionary): Contextual information (e.g., task ID, run ID).

## Consequences
- **Positive:** Enables standardized, cross-architecture eval grading and DAG reconstruction.
- **Negative:** Requires strict adherence by all architecture implementations. Log files might grow large for long runs.
