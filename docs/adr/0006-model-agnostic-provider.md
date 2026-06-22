# ADR 0006: Model-Agnostic Provider Abstraction

**Date:** 2026-06-22
**Status:** Accepted

## Context
Agent Arena needs to fairly compare different multi-agent architectures. If architectures are bound to a specific LLM provider, performance differences might stem from the model's idiosyncratic quirks rather than the architecture itself. 

## Decision
We abstract the LLM integration behind a `ModelProvider` interface that exposes a single `send_message(messages, tools, system_prompt)` method returning a `NormalizedResponse`.
- Tools expose a standard JSON Schema instead of provider-specific dicts.
- `AnthropicProvider` and `GeminiProvider` translate our normalized conversation history into their native formats.

**Parallel Tool Call Resolution Note:**
During parallel tool calls, Anthropic safely matches results to calls using a unique `tool_use_id` for each block, meaning order is loosely required. Gemini, however, matches `FunctionResponse` to `FunctionCall` strictly by function `name` without unique instance IDs. If the same function is called twice in parallel, Gemini relies on the sequential order of the responses matching the original calls. Thus, the provider abstraction guarantees that tool results are appended to the normalized history in the exact order the calls were received so `GeminiProvider` safely generates the payload.

## Consequences
- **Positive:** We can run the exact same eval traces against Claude 3.5 Sonnet and Gemini 1.5 Pro to isolate architectural impact.
- **Negative:** Increased complexity in maintaining a two-way translation layer for tool schemas and conversation histories.
