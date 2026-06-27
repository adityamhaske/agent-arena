# Agent Arena

## What is this project?
Imagine assigning a complex task to a single highly capable person, versus splitting that same task across a team of specialists. Does dividing the work introduce new kinds of errors? This project explores that question for AI. We built a testing ground to see what happens when multiple AI "agents" try to collaborate to solve customer support tickets, compared to having just one agent do everything itself.

## Why does this matter?
AI systems are increasingly moving away from single chatbots toward teams of specialized agents working together—from customer service bots handing off to billing bots, to complex coding assistants. If splitting work between agents can silently lose critical information during the handoff, that's a massive hidden risk for anyone deploying these systems in the real world.

## Who is this for?
- AI engineers building multi-agent systems
- Engineering leaders deciding whether to adopt multi-agent architectures
- Researchers studying AI reliability and failure modes

## What did this project find?
When one AI agent handed off a task to another, an important detail sometimes got lost along the way—not because the AI was confused, but because of how the handoff itself was designed. This happened every single time in one setup, and about 3 times in 10 in another. The result was an AI confidently executing the wrong action because it never received the crucial piece of information from its teammate.

## What can someone gain from this?
Engineers get a working testing harness to check their own multi-agent systems for this exact type of failure. Meanwhile, anyone evaluating AI vendor claims gets a concrete reason to ask a critical question: "How does your system guarantee that vital information isn't dropped when passing between your agents?"

## How do I explore this project?
If you're not planning to run the code, you can read the technical **Key finding** section just below this one, and then jump straight to the full writeup in [results/sweep_20260627/report.md](results/sweep_20260627/report.md).

## Key finding

Multi-agent decomposition can silently drop information at coordination boundaries, independent of model capability. On an information asymmetry trap task, `peer_to_peer` failed 100% of the time (0/5 trials) due to a rigid handoff schema; `supervisor_worker` failed probabilistically (29%) depending on whether an intermediate agent's natural-language summary happened to mention the relevant field.

→ Full report: [results/sweep_20260627/report.md](results/sweep_20260627/report.md)

## What this is

Agent Arena is an evaluation harness designed to rigorously compare different multi-agent architectures on the same tasks. Unlike standard demos, it uses a shared structured trace format to produce data-driven failure analysis. By enforcing strict, normalized tracing across all architectures, we can accurately diagnose where an agent loop breaks down—be it a logical failure, a rate-limit timeout, or a tool hallucination.

## Architectures compared

| Architecture | Description |
|---|---|
| `single_agent` | A standard ReAct loop with direct tool access. Acts as the baseline control. |
| `peer_to_peer` | Two independent agents coordinating via a rigid JSON handoff message. |
| `supervisor_worker` | A hierarchical pattern where a supervisor delegates sub-tasks to specialized workers, receiving natural-language summaries in return. |
| `debate_critic` | A proposer-critic model where a critic reviews the proposer's initial trajectory and forces revision if necessary. |

## Results summary

| Architecture | task_01 (easy) | task_02 (trap) | Notes |
|---|---|---|---|
| `single_agent` | 100% (3/3) | 100% (3/3) | Clean baseline |
| `debate_critic` | 100% (3/3) | 100% (3/3) | Most robust, highest LLM call cost |
| `peer_to_peer` | 100% (3/3) | 0% (0/5) | Deterministic coordination failure (schema drop) |
| `supervisor_worker`| 67% (2/3) | 71% (5/7) | Probabilistic coordination failure (summary compression) |

*(All runs use Gemini 2.5 Flash to isolate architectural variance from model variance)*

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
# Run with Gemini 2.5 Flash (Default)
python run_baseline.py --provider gemini

# Run with Anthropic Claude
python run_baseline.py --provider anthropic
```

To run the full 28-run evaluation sweep:
```bash
python run_all.py --providers gemini --trials 3 --sw-task02-trials 7
```

## Documentation
- **[Project Spec](docs/PROJECT_SPEC.md)**
- **[Architecture](docs/ARCHITECTURE.md)**
- **[Trace Schema](docs/TRACE_SCHEMA.md)**
- **Architecture Decision Records (ADRs):** See `docs/adr/` for the rationale behind trace formats, retry strategies, tool failure injections, and the model-agnostic provider abstraction.
