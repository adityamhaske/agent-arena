# ADR 0009: Peer-to-Peer Architecture

**Date:** 2026-06-27
**Status:** Accepted

## Context
We want to test a linear handoff model where two peer agents share context via a message bus, without a central supervisor. The key behavioral question is: can a sequential peer pipeline transfer enough structured context between agents to complete a compound task without a coordinator?

## Decision
Implement a `PeerToPeerArchitecture` with:
- **CRM Peer (Agent A)**: receives the original task, performs all CRM lookups, and produces a `HANDOFF:` structured message as its final output.
- **Ticketing Peer (Agent B)**: receives the original task prompt plus Agent A's handoff message concatenated as its prompt. Completes all ticketing operations using the extracted context.

The shared "bus" is a simple Python string: Agent A's output is appended to Agent B's input message. No LLM is involved in the handoff itself.

A `peer_handoff` trace event is emitted between the two agents, recording the handoff message, enabling the grader to verify whether context was successfully transferred.

## Trace Events
Adds: `peer_handoff`, `run_finish`.

## Consequences
- **Positive:** Simplest multi-agent topology. No coordinator overhead. Handoff is transparent and fully traceable.
- **Negative:** Agent B is entirely dependent on Agent A producing a well-structured handoff. If Agent A fails (tool errors, wrong format), Agent B has no fallback and no ability to re-query Agent A. The architecture is vulnerable to first-hop failures.
