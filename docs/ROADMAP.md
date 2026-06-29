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
  - [x] Multi-trial test harness (`run_all.py`)

- [x] **Phase 3: Multi-Agent Architectures**
  - [x] Supervisor-Worker architecture (`supervisor_worker.py`)
  - [x] Peer-to-Peer architecture (`peer_to_peer.py`)
  - [x] Debate-Critic architecture (`debate_critic.py`)
  - [x] Critic system prompt requires value-level cross-check (claimed vs actual tool results)
  - [x] `peer_handoff` is a structured TraceEvent (not informal text)
  - [x] ADRs 0005, 0006, 0008, 0009, 0010 written
  - [x] Live end-to-end verification of all 4 architectures on task_01 and task_02

- [x] **Phase 4: Comparative Analytics & Report**
  - [x] Provider × Architecture sweep matrix (4 architectures × 2 tasks, N trials, Gemini 2.5 Flash)
  - [x] task_02 (Credit Hold) — information asymmetry trap task designed and validated
  - [x] Aggregate metrics over multiple trials (28 runs total, 0 incompletes)
  - [x] Markdown reporting generator (`report_generator.py`)
  - [x] Full sweep report at `results/sweep_20260627/report.md`
  - [x] Traces organized in `results/exploratory/` and `results/sweep_20260627/`

---

## Known Gaps (Post-Phase 4)

### Grader: `coordination_failure` sub-classification (FUTURE WORK — baseline now available)
**Current state:** `coordination_failure` currently means the decision-making agent did not have
access to the critical field at the point of final action — confirmed by the grader checking
`decision_agent_saw_credit_hold`. Sweep results provide a calibration baseline for all four
architectures across both tasks.

**Gap:** The taxonomy does not yet distinguish two meaningfully different failure sub-modes:
1. **Machinery never fired** — the supervisor/peer/critic loop never started
2. **Machinery fired but produced a wrong delegation/handoff/critique** — e.g. the peer handoff
   fired but omitted `credit_hold`; the worker summary ran but compressed it out

These tell different stories. The `peer_to_peer` 0/5 result on `task_02` is machinery-fired-but-
wrong (handoff always fires; the rigid schema always drops the field). The distinction between this
and "machinery never fired" is now empirically testable using the 28-run sweep traces as ground truth.

**Plan:** Add a `coordination_failure_mode` sub-field to `GradeResult`:
- `machinery_never_fired` — all coordination counters are zero
- `handoff_data_loss` — `peer_handoff` fired but `credit_hold_in_handoff=False`
- `worker_summary_loss` — `worker_finish` fired but `credit_hold_in_worker_summary=False`
- `critic_missed_error` — critique fired but revision still produced wrong output

The 28-run sweep now provides the calibration baseline needed to implement and validate this.

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

**Phase 4 report note:** Results for peer_to_peer on task_02 are presented as
"rigid-schema peer_to_peer" to preempt the "isn't this just a bad prompt?" objection.
The schema rigidity is the architectural property under test, not the model's reasoning quality.

**Deferred:** Open-format peer_to_peer variant is future work. Do not add without
a separate task designed to distinguish schema-rigid failures from reasoning failures.
