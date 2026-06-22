# Agent Arena

Agent Arena is an evaluation harness designed to rigorously compare different multi-agent architectures (single-agent, supervisor-worker, peer-to-peer, debate/critic) on the same tasks. 

Unlike standard demos, Agent Arena uses a shared structured trace format to produce data-driven failure analysis. By enforcing strict, normalized tracing across all architectures, we can accurately diagnose where an agent loop breaks down—be it a logical failure, a rate-limit timeout, or a tool hallucination.

## Features (Phase 1)
- **Model-Agnostic Abstraction:** Supports evaluating both Anthropic (`claude-sonnet-4-6`) and Gemini (`gemini-1.5-pro`) behind a unified ReAct loop to avoid provider confounds.
- **Robust Tracing:** An append-only JSONL logger (`TraceLogger`) capable of reconstructing the exact execution DAG of the agent via parent event IDs.
- **Failure Injection:** Mock tools (Ticketing System, CRM API) that deliberately inject `429 Rate Limit` or `500 Internal Server` errors to thoroughly test an agent's recovery and retry resilience.
- **Deterministic Retries:** Utilizes `tenacity` for exponential backoff on transient LLM API infrastructure errors.

## Documentation
- **[Project Spec](docs/PROJECT_SPEC.md)**
- **[Architecture](docs/ARCHITECTURE.md)**
- **[Trace Schema](docs/TRACE_SCHEMA.md)**
- **Architecture Decision Records (ADRs):** See `docs/adr/` for the rationale behind trace formats, retry strategies, tool failure injections, and the model-agnostic provider abstraction.

## Setup

1. Install dependencies:
   ```bash
   pip install anthropic google-generativeai tenacity
   ```
2. Export your API keys:
   ```bash
   export ANTHROPIC_API_KEY="your-anthropic-key"
   export GEMINI_API_KEY="your-gemini-key"
   ```

## Usage

To run the baseline single-agent architecture against the Customer Escalation eval task:

```bash
# Run with Gemini (Default)
python run_baseline.py --provider gemini

# Run with Anthropic
python run_baseline.py --provider anthropic
```

The script will:
1. Initialize a local SQLite database (`eval_db.sqlite`) representing the ticketing system state.
2. Inject a 30% failure rate into the Mock CRM API.
3. Initiate the Agent ReAct loop to solve the escalation task.
4. Output a trace summary and generate a `.jsonl` trace file in the root directory.
