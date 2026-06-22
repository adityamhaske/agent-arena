# ADR 0004: Agent LLM Retry Strategy

**Date:** 2026-06-22
**Status:** Accepted

## Context
Agent LLM calls are subject to transient API errors such as 429 Rate Limits and 500 Internal Server Errors. In an evaluation harness, we want to isolate agent logic flaws from these transient infrastructure issues.

## Decision
We will wrap all Anthropic API calls with an exponential backoff retry mechanism using the `tenacity` Python library.
- We will catch specific transient errors from the LLM provider (e.g., RateLimitError, APIConnectionError, InternalServerError).
- We will perform a maximum of 5 retries.
- We will use exponential backoff with a max wait time of 60 seconds.

## Consequences
- **Positive:** Agent evals are much more stable and deterministic; we won't fail an eval just because the API hiccupped.
- **Negative:** A persistently failing API could cause long delays during evaluation runs.
