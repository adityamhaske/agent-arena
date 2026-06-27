# ADR 0005: Supervisor-Worker Architecture

**Date:** 2026-06-27
**Status:** Accepted

## Context
For evaluation purposes, we need to test whether a two-tier delegation model can outperform a single agent on multi-domain tasks (CRM + ticketing). The key behavioral question is: does decomposing a task and routing sub-tasks to specialized workers reduce tool-call errors and improve task completion versus a single generalist agent?

## Decision
Implement a `SupervisorWorkerArchitecture` with:
- **Supervisor Agent**: receives the full task, decomposes it into sub-tasks using two virtual delegation "tools" (`delegate_to_crm_worker`, `delegate_to_ticketing_worker`), and assembles the final answer from worker results.
- **CRM Worker**: runs its own full ReAct loop with only the `get_customer_profile` tool.
- **Ticketing Worker**: runs its own full ReAct loop with only the ticketing tools.

Virtual delegation tools are intercepted at the architecture layer (not by an LLM provider). The architecture runs each worker as a full `Agent` instance, injecting the worker's events into the shared trace file with the correct `parent_event_id` hierarchy.

## Trace Events
Adds: `supervisor_start`, `supervisor_finish`, `worker_start`, `worker_finish`.

## Consequences
- **Positive:** Worker specialization prevents tool-namespace confusion. Worker tool errors are isolated from the supervisor's reasoning.
- **Negative:** Each delegation requires one additional round-trip through the supervisor's LLM, adding latency. Context compression loss is a risk: workers receive only the instruction string, not the full conversation history.
