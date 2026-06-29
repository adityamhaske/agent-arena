# Trace Schema

The canonical definition of the TraceEvent schema, as decided in ADR 0001.

## TraceEvent Schema

All traces are stored in JSONL format, where each line is a JSON object with the following schema:

- `event_id` (String): A UUID identifying the event.
- `parent_event_id` (String | null): A UUID pointing to the parent event. Used for DAG reconstruction.
- `timestamp` (String): ISO-8601 formatted datetime string.
- `event_type` (String): Categorical type of the event. See full list below.
- `payload` (Object): The main body of the event. Varies by `event_type`.
- `metadata` (Object): Optional dictionary containing context (e.g. `run_id`, `task_id`).

---

## Event Types & Payloads

### Core (all architectures)
- **`run_start`**: Contains initial inputs and configuration. First event in every trace.
- **`llm_call`**: Payload contains `messages`, `system_prompt`, `provider`, `model`, and the returned `response`.
- **`tool_call`**: Payload contains `tool_name`, `tool_call_id`, and `arguments`.
- **`tool_result`**: Payload contains `tool_call_id`, `tool_name`, `result`, and `error` (boolean).
- **`agent_step`**: Represents a logical iteration in the agent's ReAct loop.
- **`error`**: Payload contains `error_type`, `message`, and `traceback`.
- **`agent_finish`**: Final event for single-agent runs. Contains the agent's last output.
- **`run_finish`**: Final event for multi-agent runs. Contains `architecture` and `final_output`.

### Supervisor-Worker (`supervisor_worker.py`)
- **`supervisor_start`**: Emitted when the supervisor agent begins executing. Contains the task prompt.
- **`supervisor_finish`**: Emitted when the supervisor has assembled and returned its final answer.
- **`worker_start`**: Emitted when a worker agent begins. Payload contains `worker_name` and the delegated instruction string.
- **`worker_finish`**: Emitted when a worker completes. Payload contains `worker_name` and `result` — a free-form natural-language summary returned to the supervisor. **Note:** whether the `credit_hold` field appears in this summary is the key grader signal for `task_02`.

### Peer-to-Peer (`peer_to_peer.py`)
- **`peer_handoff`**: Emitted between Agent A and Agent B. Payload contains `from_agent`, `to_agent`, and `handoff_message` — the fixed-format `HANDOFF: customer_id=<id>, tier=<tier>, name=<name>, status=<status>` string produced by Agent A. The grader checks this payload for `credit_hold` to detect information loss.

### Debate-Critic (`debate_critic.py`)
- **`critic_review`**: Emitted after the proposer's first pass. Payload contains `draft`, `tool_summary` (extracted from the trace), and `critique` — the critic's structured verdict.
- **`revision_start`**: Emitted when the proposer begins its corrective pass after receiving the critique.
- **`revision_finish`**: Final event for debate-critic runs. Contains the proposer's revised output.
