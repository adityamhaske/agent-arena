# ADR 0002: Baseline Fairness

**Date:** 2026-06-22  
**Status:** Accepted  

## Context
A major challenge when evaluating multi-agent architectures is proving that the multi-agent decomposition is responsible for a failure, rather than just bad prompting or limited context. In many real-world systems, multi-agent architectures explicitly restrict the context or tools given to any individual agent (e.g., a "CRM Worker" only has CRM tools; a "Ticketing Worker" only has ticketing tools). 

If we artificially restrict the baseline `single_agent` in the same way, we cripple its ability to function as a true control group.

## Decision
We will build the `single_agent` baseline architecture with completely unrestricted access to all tools (CRM, ticketing) and a full, unfiltered context window. 

## Consequences
By guaranteeing a completely unhandicapped baseline, we establish a clean control. This ensures that when multi-agent architectures fail on the information asymmetry trap (`task_02`), those failures can be definitively interpreted as architecture-driven (information loss at boundaries) rather than the result of rigging or handicapping the baseline. The `single_agent` passed 100% of trials cleanly precisely because of this fairness guarantee.
