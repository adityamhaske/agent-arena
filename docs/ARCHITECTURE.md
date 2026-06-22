# Architecture

The architectural structure of Agent Arena, derived from ADRs 0001, 0004, and 0005.

## Repository Structure

- `core/`: Base abstractions and shared infrastructure.
  - `trace.py`: Implements `TraceEvent` and `TraceLogger` (ADR 0001).
  - `agent.py`: Base Agent class wrapping the LLM provider, featuring `tenacity`-based retries (ADR 0004) and trace logging.
  - `tools/`: Mock tool implementations supporting failure injection (ADR 0005).
  - `architectures/`: Specific multi-agent or single-agent orchestration logic.
- `evals/`: Evaluation harness and tasks.
  - `tasks/`: Individual evaluation task definitions and grader function stubs.

## Module Boundaries

1. **Trace Logger:** An append-only JSONL logger. All architectural components emit `TraceEvent` objects to the logger.
2. **Tools:** Independent, stateful mock services returning standard JSON schema.
3. **Model Providers:** Translates standard schema and message history into provider-specific API calls.
4. **Agent:** Encapsulates the ReAct loop and interacts with tools. It relies completely on the `ModelProvider` interface.
5. **Architectures:** Wires together multiple agents, tools, and specific providers to solve a task.
