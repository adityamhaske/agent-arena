# Roadmap — Agent Arena

- [x] **Phase 1: Foundation & Baseline**
  - [x] TraceEvent dataclass and `TraceLogger` DAG reconstruction
  - [x] Model-agnostic `ModelProvider` wrappers (Anthropic, Gemini)
  - [x] Mock tools with deterministic failure injections
  - [x] Single-agent baseline execution harness (`run_baseline.py`)

- [x] **Phase 2: Evaluation Grading & Failure Categorization**
  - [x] Core evaluation scorer interface
  - [x] Multi-dimensional failure categorization:
    - `task_failure` — machinery ran but produced wrong output
    - `coordination_failure` — architecture's coordination machinery never activated
    - `tool_error_unrecovered` — injected failures not recovered by agent ReAct loop
    - `incomplete` — run crashed, quota exhausted, or hit iteration limit
  - [x] Coordination-specific metrics: `num_delegations`, `num_workers_invoked`,
        `num_handoffs`, `num_critique_rounds`, `num_revisions`
  - [x] `has_finished` accepts `run_finish`/`supervisor_finish`/`revision_finish`
        in addition to `agent_finish` (multi-agent architectures)
  - [x] Grader verified on live Phase 1 traces
  - [ ] Multi-trial test harness

- [x] **Phase 3: Multi-Agent Architectures**
  - [x] Supervisor-Worker architecture (`supervisor_worker.py`)
  - [x] Peer-to-Peer architecture (`peer_to_peer.py`)
  - [x] Debate-Critic architecture (`debate_critic.py`)
  - [x] Critic system prompt requires value-level cross-check (claimed vs actual tool results)
  - [x] `peer_handoff` is a structured TraceEvent (not informal text)
  - [x] ADRs 0005, 0006, 0007 written
  - [ ] Live end-to-end verification of all 3 architectures (pending stable API quota)

- [ ] **Phase 4: Comparative Analytics & Report**
  - [ ] Provider × Architecture sweep matrix (4 architectures × 2 providers, N trials)
  - [ ] Aggregate metrics over multiple trials
  - [ ] Markdown reporting generator (`results/report.md`)

---

## Known Gaps (Pre-Phase 4)

### Grader: `coordination_failure` sub-classification (DEFERRED)
**Current state:** `coordination_failure` means "the architecture's coordination machinery
never activated at all" — no delegations, no handoffs, no critiques, no tool calls fired.

**Gap:** This does not distinguish two meaningfully different failure modes:
1. **Machinery never fired** — the supervisor/peer/critic loop never started (e.g. first LLM call crashed)
2. **Machinery fired but produced a wrong delegation/handoff/critique** — e.g. the supervisor delegated
   to the wrong worker, the peer passed an empty handoff, or the critic approved a hallucinated answer

These are different stories for the Phase 4 report. A supervision failure where the delegation logic
is correct but the worker returned bad data is architecturally different from a case where the
supervisor never even tried to delegate.

**Plan:** Before generating the Phase 4 report, add a `coordination_failure_mode` sub-field:
- `machinery_never_fired` — all coordination counters are zero
- `wrong_delegation` — supervisor delegated but worker produced wrong output (detected via db_correct=False + num_workers_invoked > 0)
- `handoff_data_loss` — handoff fired but Agent B produced wrong output despite it (num_handoffs > 0 + task_failure)
- `critic_missed_error` — critique fired but revision still produced wrong output (num_critique_rounds > 0 + task_failure)

Do not add this until we have passing runs of each architecture to calibrate against.

### peer_to_peer: rigid handoff schema (DELIBERATE DESIGN CHOICE, NOT A BUG)
**Current state:** The CRM Peer's system prompt hard-codes the handoff format:
`HANDOFF: customer_id=<id>, tier=<tier>, name=<name>, status=<status>`

**What this tests:** The real-world pattern of under-specified handoff payloads —
API contracts between agents that were designed for a known set of fields and never
updated when new fields (e.g. `credit_hold`) were added to the upstream system.
This is the dominant failure mode in production multi-agent systems, not "the model
chose a bad format."

**What this does NOT test:** Open-format peer_to_peer, where the CRM Peer decides
what to include in the handoff and the Ticketing Peer parses free-form context.
An open-format variant would test a different (and arguably less realistic) failure mode.

**Phase 4 report note:** Results for peer_to_peer on task_02 should be presented as
"rigid-schema peer_to_peer" to preempt the "isn't this just a bad prompt?" objection.
The schema rigidity is the architectural property under test, not the model's reasoning quality.

**Deferred:** Open-format peer_to_peer variant is future work. Do not add without
a separate task designed to distinguish schema-rigid failures from reasoning failures.

