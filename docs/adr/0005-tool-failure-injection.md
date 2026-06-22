# ADR 0005: Tool Failure Injection

**Date:** 2026-06-22
**Status:** Accepted

## Context
To evaluate an agent's robustness and error recovery capabilities within its tool loop, we need tools that fail realistically. Perfect, non-failing tools do not test an agent's true capability to handle real-world API integrations.

## Decision
Mock tools implemented in `core/tools/` will support a configuration to inject failures deterministically or randomly. 
- The tools will optionally raise exceptions like RateLimitError, TimeoutError, or 500 Internal Server Error when invoked.
- This configuration can be passed during tool initialization.
- The agent loop is expected to catch tool-level errors (by capturing the stack trace/error message) and feed them back into the LLM as tool results to observe if the LLM can self-correct or retry gracefully.

## Consequences
- **Positive:** Allows for deep evaluation of agent resilience and error-handling ReAct loops.
- **Negative:** Increases complexity in tool implementation. Evals must carefully orchestrate when and how failures are injected to remain deterministic.
