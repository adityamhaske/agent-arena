# Study: Multi-Agent Handoff Information Loss

> **Status: complete and frozen.** This study finished on 2026-06-27. Its code is
> kept for reproducibility and is not under active development — bug fixes are
> welcome, new features belong in the [universal arena](../../README.md) instead.
> It is deliberately **not** part of the installable `agent-arena` package and has
> its own dependencies (see [Setup](#setup)).

Does splitting a task across multiple agents lose information at the handoff?

**It does — and independently of how capable the model is.** That is the finding
this directory exists to support.

→ **Full report: [results/sweep_20260627/report.md](results/sweep_20260627/report.md)**

## Key finding

Multi-agent decomposition can silently drop information at coordination
boundaries, independent of model capability. On an information asymmetry trap
task, `peer_to_peer` failed 100% of the time (0/5 trials) due to a rigid handoff
schema; `supervisor_worker` failed probabilistically (29%) depending on whether
an intermediate agent's natural-language summary happened to mention the
relevant field.

## What is this?

Imagine assigning a complex task to a single highly capable person, versus
splitting that same task across a team of specialists. Does dividing the work
introduce new kinds of errors? This study explores that question for AI. We built
a testing ground to see what happens when multiple AI "agents" try to collaborate
to solve customer support tickets, compared to having just one agent do
everything itself.

## Why does it matter?

AI systems are increasingly moving away from single chatbots toward teams of
specialized agents working together — from customer service bots handing off to
billing bots, to complex coding assistants. If splitting work between agents can
silently lose critical information during the handoff, that's a massive hidden
risk for anyone deploying these systems in the real world.

## Who is it for?

- AI engineers building multi-agent systems
- Engineering leaders deciding whether to adopt multi-agent architectures
- Researchers studying AI reliability and failure modes

## What did it find?

When one AI agent handed off a task to another, an important detail sometimes got
lost along the way — not because the AI was confused, but because of how the
handoff itself was designed. This happened every single time in one setup, and
about 3 times in 10 in another. The result was an AI confidently executing the
wrong action because it never received the crucial piece of information from its
teammate.

## What can someone gain from this?

Engineers get a working testing harness to check their own multi-agent systems
for this exact type of failure. Meanwhile, anyone evaluating AI vendor claims
gets a concrete reason to ask a critical question: "How does your system
guarantee that vital information isn't dropped when passing between your
agents?"

## How it works

The harness forces every architecture to emit the same normalized trace format.
That is what makes the result trustworthy: it lets the grader separate a *task
failure* (the agent had the right data and still chose badly) from a
*coordination failure* (the architecture prevented the agent from ever seeing the
data). Without that separation, both look like "the model got it wrong."

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

This study is not installed by `pip install -e .` at the repo root — that
installs the universal arena only. Install its dependencies directly:

```bash
pip install anthropic google-generativeai tenacity
export ANTHROPIC_API_KEY="your-anthropic-key"
export GEMINI_API_KEY="your-gemini-key"
```

## Usage

Run the commands below **from this directory** (`studies/multi_agent_handoff/`).
The scripts resolve `core/` and `evals/` relative to themselves and write output
to `results/` relative to your working directory.

```bash
cd studies/multi_agent_handoff
```

Run the baseline single-agent architecture against the Customer Escalation eval
task:

```bash
# Run with Gemini 2.5 Flash (Default)
python run_baseline.py --provider gemini

# Run with Anthropic Claude
python run_baseline.py --provider anthropic
```

Run the full 28-run evaluation sweep:

```bash
python run_all.py --providers gemini --trials 3 --sw-task02-trials 7
```

Regenerate the report from a sweep manifest:

```bash
python report_generator.py results/sweep_<timestamp>.json
```

## Layout

| Path | What it holds |
|---|---|
| `core/` | Providers, agent loop, mock tools, trace logger, and the four architectures |
| `evals/` | The grader and the two eval task definitions |
| `run_baseline.py` | Single run: one architecture, one task |
| `run_all.py` | Multi-trial sweep across architectures and tasks |
| `report_generator.py` | Aggregates a sweep manifest into a markdown report |
| `results/sweep_20260627/` | The committed 28-run sweep: traces, summary, and report |

## Documentation

- **[Report](results/sweep_20260627/report.md)** — the full writeup
- **[Project Spec](docs/PROJECT_SPEC.md)** — the north star and the key finding
- **[Architecture](docs/ARCHITECTURE.md)** — pipeline boundaries and each architecture
- **[Tasks and Evals](docs/TASKS_AND_EVALS.md)** — the two tasks and their success criteria
- **[Trace Schema](docs/TRACE_SCHEMA.md)** — the normalized trace format
- **[Roadmap](docs/ROADMAP.md)** — phase history and known gaps
- **ADRs 0001–0010** live in the repo-wide log at [`docs/adr/`](../../docs/adr/) —
  see [DECISIONS.md](../../docs/DECISIONS.md)
