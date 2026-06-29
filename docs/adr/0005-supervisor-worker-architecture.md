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

## Empirical Results (Phase 4 sweep — 2026-06-27)

**task_01 (Customer Escalation):** 67% pass rate (2/3 trials). The one failure was a `task_failure`: the Ticketing Worker hallucinated a successful `update_ticket` call without actually invoking the tool. This is a general LLM reliability issue, not evidence of information loss at the architectural boundary. With only 3 trials, we cannot reliably distinguish whether this failure rate differs from the `single_agent` baseline; more trials would be required to detect a meaningful difference.

**task_02 (Credit Hold — information asymmetry trap):** 71% pass rate (5/7 trials). The two failures were `coordination_failure`: the CRM Worker's natural-language summary did not include the `credit_hold=True` flag, so the Supervisor never had access to it when making the final ticketing decision. This is probabilistic — whether the field appears in the free-text summary is model-dependent, not guaranteed by the architecture.

## Consequences
- **Positive:** Worker specialization prevents tool-namespace confusion. Worker tool errors are isolated from the supervisor's reasoning. The architecture passed `task_02` 71% of the time — better than `peer_to_peer` (0%), though worse than `single_agent` and `debate_critic` (both 100%).
- **Negative:** Each delegation requires one additional round-trip through the supervisor's LLM, adding latency and LLM call cost (~10 calls per run vs 4 for single_agent). Context compression loss is a confirmed risk: the CRM Worker's free-text summary is the sole channel for passing CRM data to the Supervisor, and field omission is empirically confirmed as the failure mode for `task_02`.
