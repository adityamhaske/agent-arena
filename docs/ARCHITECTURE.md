# Architecture

The architectural structure of Agent Arena, governed by ADRs 0001 through 0006.

## Pipeline Boundaries

Agent Arena is structured as an end-to-end evaluation pipeline, moving from execution to structured grading and reporting:

1. **Model Providers (`core/providers.py`)**: Abstracts Anthropic and Gemini APIs behind a unified interface, ensuring cross-provider compatibility (ADR 0006).
2. **Tools (`core/tools/`)**: Independent, stateful mock services (Ticketing, CRM) that return standard JSON schemas and support deterministic failure injection (ADR 0005b).
3. **Trace Logger (`core/trace.py`)**: An append-only JSONL logger. Every component emits `TraceEvent` objects, forming a reconstructable execution DAG (ADR 0001).
4. **Architectures (`core/architectures/`)**: The coordination patterns under test, wiring together agents and tools (see below).
5. **Grader (`evals/grader.py`)**: Evaluates traces against database state and enforces a strict taxonomy: `task_failure`, `coordination_failure`, `tool_error_unrecovered`, or `incomplete` (ADR 0003).
6. **Report Generator (`report_generator.py`)**: Aggregates run data from `results/` into statistical summaries and markdown reports.

## Architectures Under Test

All architectures rely on a base `Agent` equipped with `tenacity`-based retries (ADR 0004) and trace logging. To ensure fairness, the baseline architecture has unrestricted tool access (ADR 0002).

### Single Agent (`single_agent.py`)
- **Agents:** One central agent.
- **Tool Access:** Unrestricted (has access to both CRM and Ticketing tools).
- **Communication:** None required. The agent interacts directly with all tools in a standard ReAct loop.

### Peer to Peer (`peer_to_peer.py`)
- **Agents:** Two independent agents (CRM Peer and Ticketing Peer).
- **Tool Access:** Strictly partitioned. CRM Peer only has CRM tools; Ticketing Peer only has Ticketing tools.
- **Communication:** Agents communicate sequentially via a rigid, fixed-format handoff string (e.g. `HANDOFF: customer_id=<id>, tier=<tier>, name=<name>, status=<status>`). The CRM Peer passes this string to the Ticketing Peer.

### Supervisor Worker (`supervisor_worker.py`)
- **Agents:** One Supervisor agent and specialized Worker agents (e.g., CRM Worker, Ticketing Worker).
- **Tool Access:** The Supervisor has no direct tools except `delegate_to_worker`. The Workers have partitioned tool access.
- **Communication:** The Supervisor delegates sub-tasks to Workers. The Workers execute their tools and return a free-form, natural-language summary back to the Supervisor (`worker_finish` event).

### Debate Critic (`debate_critic.py`)
- **Agents:** A Proposer agent and a Critic agent.
- **Tool Access:** Both have unrestricted tool access.
- **Communication:** The Proposer drafts a trajectory/action plan. The Critic reviews the proposed action against the constraints and forces a revision loop (`critic_review`) if it detects logical flaws.
