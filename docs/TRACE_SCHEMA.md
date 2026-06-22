# Trace Schema

The canonical definition of the TraceEvent schema, as decided in ADR 0001.

## TraceEvent Schema

All traces are stored in JSONL format, where each line is a JSON object with the following schema:

- `event_id` (String): A UUID identifying the event.
- `parent_event_id` (String | null): A UUID pointing to the parent event. Used for DAG reconstruction.
- `timestamp` (String): ISO-8601 formatted datetime string.
- `event_type` (String): One of: `run_start`, `agent_step`, `llm_call`, `tool_call`, `tool_result`, `error`.
- `payload` (Object): The main body of the event. Varies by `event_type`.
- `metadata` (Object): Optional dictionary containing context (e.g. `run_id`, `task_id`).

### Event Types & Payloads
- **run_start**: Contains initial inputs and configuration.
- **agent_step**: Represents a logical iteration in the agent's loop.
- **llm_call**: Payload contains `messages`, `system_prompt`, `provider`, `model`, and the returned `response`.
- **tool_call**: Payload contains `tool_name`, `tool_call_id`, and `arguments`.
- **tool_result**: Payload contains `tool_call_id`, `tool_name`, `result`, and `error` (boolean).
- **error**: Payload contains `error_type`, `message`, and `traceback`.
