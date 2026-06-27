# ADR 0004: Retry Strategy — Two Distinct Layers

**Date:** 2026-06-22  
**Updated:** 2026-06-27  
**Status:** Accepted (Clarified)

## Context
Agent evaluation runs are subject to two fundamentally different categories of transient failures:

1. **LLM infrastructure errors** — 429 Rate Limits and 500 errors from the model API (Anthropic or Gemini), which have nothing to do with task logic.
2. **Tool-level failures** — Errors raised by mock tools (e.g. `MockCustomerAPI.InternalServerError`), which are *intentionally injected* to test whether the agent can recover via its own reasoning.

These two failure types require different retry mechanisms and must not be conflated.

## Decision

### Layer 1 — `tenacity` exponential backoff (LLM infrastructure only)
Each `ModelProvider` implementation wraps its raw API call (`_call_api`) with `tenacity` exponential backoff:
- **Catches:** Provider-specific transient errors only — `anthropic.RateLimitError`, `anthropic.APIConnectionError`, `anthropic.InternalServerError` for Anthropic; `google.api_core.exceptions.ResourceExhausted`, `ServiceUnavailable`, `InternalServerError` for Gemini.
- **Does NOT catch:** `MockCustomerAPI.RateLimitError` or `MockCustomerAPI.InternalServerError` — these are plain Python exceptions with no relation to the provider exception hierarchy.
- **Config:** max 5 attempts, exponential backoff min=2s/max=60s (Anthropic), min=15s/max=60s (Gemini free tier).
- **Visible in traces:** No — tenacity retries happen inside `_call_api` before the trace system sees them. They are invisible to the trace DAG by design: the trace should show *task logic*, not infrastructure noise.

### Layer 2 — Agent ReAct loop (tool-level)
When a tool raises an exception, `agent.py` catches it at line 121, converts it to an error string, and feeds it back to the LLM as a `tool_result` with `is_error: true`. The LLM then reasons about the error and may choose to call the tool again in the next iteration.

- **This is the agent's own retry capability** — it is a test of the model's reasoning and the architecture's resilience.
- **Visible in traces:** Yes — every tool error and every subsequent retry call appears as distinct `tool_call` / `tool_result` events in the JSONL, making it directly measurable.

## Design Rationale

**tenacity handles transport-level failures from the real provider SDKs only.** Tool-level application errors raised by our mock tools are intentionally NOT caught by tenacity and are left entirely to the agent's own ReAct-loop reasoning to recover from. This is a deliberate design choice, not an oversight: tool-error recovery is itself something we want to measure and grade. Silencing mock tool failures through infrastructure-level retries would hide the behavioral signal we are trying to capture — namely, whether an agent architecture can detect, reason about, and retry a failed tool call on its own, without any scaffolding assistance.


## Verification (confirmed via live trace)
In `trace_baseline_20260626_215009.jsonl` (80% failure rate run):
- Events 5–6: First `tool_call` → `tool_result` with `error: true`. **No sleep between events** (timestamps differ by ~1ms), proving tenacity did NOT fire here — the mock exception type was not in its retry list.
- Events 7–8: LLM received the error, reasoned about it, issued a second `tool_call` (~3 seconds later, LLM inference time). **This is a ReAct-level retry, not tenacity.**
- Events 9–10: Second `tool_call` → `tool_result` with `error: true` again.
- Events 11–12: LLM gave up and produced a final text response.

## Consequence for Grading
The grader's `tool_error_unrecovered` category correctly measures Layer 2 failures (the agent failed to reason its way through tool errors). Layer 1 failures (tenacity exhausted) produce an `incomplete` category because the `agent_finish` event is never emitted.

## Consequences
- **Positive:** The two layers are cleanly separated. Infrastructure retries are invisible noise-filters; tool-level retries are meaningful behavioral signal.
- **Negative:** If an architect expects tenacity to back off on mock tool errors, it will not. Tool-resilience is a first-class evaluation dimension — it is intentionally the agent's responsibility.

