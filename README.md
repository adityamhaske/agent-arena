# Agent Arena

Two independent evaluation systems that share a philosophy — **structured
evidence over vibes** — and answer opposite questions about LLM systems.

| | Question it answers | What varies | What is held fixed | Where |
|---|---|---|---|---|
| **Universal arena** | Which model should *my* project use, on *my* criteria? | The model | The task, the architecture | `agent_arena/`, `projects/` — [docs/UNIVERSAL_ARENA.md](docs/UNIVERSAL_ARENA.md) |
| **Multi-agent study** | Does splitting a task across agents lose information at the handoff? | The architecture | The model, the task | `studies/multi_agent_handoff/` — [its README](studies/multi_agent_handoff/README.md) |

They share no code. Zero imports cross between them.

## Why two projects, and why they belong together

Any claim about an LLM system is a claim about one of two variables, and most
evaluations quietly confound them. When a multi-agent pipeline fails, was it the
*model* being dumb, or the *architecture* dropping data on the floor? You cannot
answer that by varying both at once.

So each project pins one variable and moves the other:

```
                 varies the MODEL
                        ▲
                        │
          Universal arena│  "we picked Haiku and quality dropped"
       (task held fixed) │   → a model question
                        │
    ────────────────────┼────────────────────►  varies the ARCHITECTURE
                        │
                        │  Multi-agent study   "we split it into agents
                        │  (model held fixed)   and it broke"
                        │                       → an architecture question
```

That is the whole relationship. The study proves the architecture axis is real —
that a *coordination* failure exists and is separable from a capability failure.
The arena is the tool for the model axis, built afterward and informed by it.

The study is also why the arena's design is what it is: **the study's finding is
that you cannot diagnose a system whose failures you cannot categorize.** Both
codebases therefore refuse to reduce a run to a single pass/fail number — the
study emits a normalized trace you can replay, the arena emits a scored,
weighted, per-criterion leaderboard plus a queryable database.

---

# 1. Universal Arena

**The question:** you have a task and a budget. Which model should you actually
ship, and what does that choice cost you?

## Why it's unique

Most model comparisons are public benchmarks — MMLU, LMArena, a vendor's own
chart. Those tell you how a model does on *someone else's* task, aggregated over
criteria you didn't choose. That is nearly useless for a shipping decision,
because your accuracy floor, latency budget, and price ceiling are yours.

The arena inverts that. It knows nothing about any task:

- **A project is a folder, not code.** `config.yaml` + `tests.yaml`. To evaluate
  something completely different, copy the template and change the files. There
  is no second code path and no plugin to write.
- **You define what "best" means.** Weights across accuracy/cost/latency, a
  budget per 1k calls, a latency target, and **hard constraints** — a model under
  your accuracy floor is not ranked low, it's `DISQUALIFIED` with the reason
  printed. A leaderboard that ranks an unusable model 4th is lying to you.
- **It is honest about resolution.** When the top two are within 0.02, the report
  says so and suggests more trials, rather than implying a 12-case sweep can
  separate them.
- **It runs offline.** Deterministic `mock:` models with fixed accuracy/latency/
  price let you prove your scorers and weights behave *before* spending anything.
  Both example projects run with no API key.
- **Local models are first-class.** Anything with an OpenAI-compatible endpoint
  (Ollama, vLLM, LM Studio) sits in the same run as a frontier API model.
- **The engine is stdlib-only.** PyYAML is the single dependency and even that is
  optional — JSON config works without it. Every provider SDK imports lazily, so
  you install only what you call.

## Where

| Path | What it holds |
|---|---|
| `agent_arena/` | The engine — config, runner, metrics, store, report |
| `agent_arena/connectors/` | Providers: Anthropic, OpenAI, Gemini, LiteLLM, local, mock |
| `agent_arena/scorers/` | The 10 built-in eval types |
| `agent_arena/templates/` | What `arena init` copies |
| `agent_arena/web/` | The browser UI — server, JSON API, plain-English layer |
| `projects/support_triage/` | Example 1 — high-volume classification, offline |
| `projects/doc_extraction/` | Example 2 — structured JSON extraction, offline |
| `projects/local_demo/` | Example 3 — models on your own machine |
| `tests/` | 258 tests covering the engine and the UI |

## How to use it

```bash
pip install -e .          # engine only; add [anthropic], [openai], [gemini], [all]
```

Run an example to see a real leaderboard immediately — no API key needed:

```bash
arena evaluate --project projects/support_triage
```

```
  #  model         id             composite  accuracy  cost   latency  status
  1  sim_small     mock:small     0.853      83.3%     $0.06  190ms    ranked
  2  sim_frontier  mock:frontier  0.750      97.6%     $0.30  1,500ms  ranked
  3  sim_balanced  mock:balanced  0.744      85.7%     $0.18  620ms    ranked
  -  sim_tiny      mock:tiny      —          50.0%     $0.02  90ms     DISQUALIFIED

  Winner: sim_small  (accuracy 83.3%, cost $0.06, latency 190ms)
  ✗ sim_tiny: accuracy 50.0% below the required 70.0%
```

Note the winner is not the most accurate model. At this volume, with these
weights, the small one wins — and that is the entire point of the tool.

### Without a terminal

The people who make this decision — who owns the support queue, what the budget
is, how slow is too slow — are usually not the people who write YAML. So the
same engine has a browser front end:

```bash
arena ui                    # opens http://localhost:8420
```

It asks *what job is the AI doing?* in plain language, writes the same
`config.yaml` a developer would have written, and reports the outcome as
sentences rather than scores:

> **Use Small/fast (simulated).**
> It gets 83 out of 100 right, costs 6¢ per 1,000 uses, and replies in 190
> milliseconds (instant).
> *Small/fast is not the most accurate — Frontier-class gets about 14 more
> answers right in every 100 — but it is 4.9× cheaper and 7.9× faster.*
>
> **Cannot use: Tiny (simulated).** It only gets 50 out of 100 right, which is
> below the floor you set.

Three things it does that the CLI does not:

- **A wizard instead of a config file** — pick the kind of job from seven plain
  descriptions ("sort things into categories", "pull specific details out of
  text"), and the right scorer, prompt and starting weights are chosen for you.
- **What-if sliders** — change how much you care about accuracy, cost or speed
  and the ranking is recalculated *from the answers already collected*. No new
  API calls, no new spend. It runs the real `build_leaderboard`, so a what-if
  and a fresh run can never disagree.
- **Plain-English disqualifications** — the reason a model was ruled out, plus
  whether the fix is a better model or a more realistic requirement.

It is stdlib-only like the engine (no Flask, no npm, no CDN), binds to localhost,
and works offline. `arena ui --projects-dir path/to/projects --port 8421` if you
keep projects elsewhere.

### Your own project

```bash
arena init projects/my_project     # scaffold config.yaml + tests.yaml + scorers/
# edit the two files
arena validate --project projects/my_project              # config, tests, credentials
arena evaluate --project projects/my_project --dry-run    # plan + cost estimate
arena evaluate --project projects/my_project
```

**`config.yaml`** is the whole contract:

```yaml
models:                          # what to compare
  - key: sim_small
    model: mock:small
    card: {input_usd_per_mtok: 1, output_usd_per_mtok: 5}
  - key: opus_5
    model: claude-opus-5         # skipped, not failed, if the key is missing

defaults: {system: "...", max_tokens: 8, temperature: 0}
run:      {trials: 3, concurrency: 8, timeout_s: 30}

metrics:                         # what "best" means to you
  weights: {accuracy: 0.55, cost: 0.25, latency: 0.20}
  cost:    {budget_usd_per_1k_calls: 2.0}
  latency: {target_ms: 800}

constraints:                     # non-negotiables → DISQUALIFIED
  min_accuracy: 0.70
  max_latency_p95_ms: 4000

scorers:
  default: classification
  options: {classification: {labels: [billing, technical, ...]}}
```

**`tests.yaml`** is your cases:

```yaml
tests:
  - id: double_charge
    input: "I was charged twice for the same order this month."
    reference: billing
    tags: [billing, easy]
```

### Scoring

Ten built-in eval types, no scorer code required: `classification`,
`exact_match`, `contains`, `regex`, `numeric`, `json_match`, `semantic`,
`code_exec`, `llm_judge`, `manual`. Run `arena scorers` to see them. Drop a
Python file in `scorers/` for grading only you can write, and `hooks.py` to touch
outputs before grading.

### The rest of the CLI

```bash
arena models   --project <p>   # model cards: price, context window, features
arena tests    --project <p>   # what cases will run
arena report   --project <p> --run-id <id>   # re-show a stored run
arena history  --project <p>   # past runs, and regressions between them
```

Every run lands in a SQLite database (`results/arena.sqlite`) alongside the
Markdown and JSON reports, so you can query across runs rather than re-running.

**Full reference:** [docs/UNIVERSAL_ARENA.md](docs/UNIVERSAL_ARENA.md) ·
**Walkthrough with local models:** [demo.md](demo.md) ·
**Sample output:** [docs/EXAMPLE_REPORT.md](docs/EXAMPLE_REPORT.md)

---

# 2. Multi-Agent Handoff Study

**The question:** you split a task across specialized agents. Does the split
itself introduce failures that no single agent would have had?

> **Status: complete and frozen.** Finished 2026-06-27, kept for
> reproducibility. Not part of the installable package; it has its own
> dependencies.

## The finding

**Multi-agent decomposition silently drops information at coordination
boundaries, independent of model capability.** On a task where one agent holds a
flag another agent needs:

| Architecture | task_01 (easy) | task_02 (trap) | What happened |
|---|---|---|---|
| `single_agent` | 100% (3/3) | 100% (3/3) | Clean baseline |
| `debate_critic` | 100% (3/3) | 100% (3/3) | Most robust, highest call cost |
| `peer_to_peer` | 100% (3/3) | **0% (0/5)** | Rigid handoff schema dropped the field every time |
| `supervisor_worker` | 67% (2/3) | **71% (5/7)** | Worker's summary mentioned the field — or didn't |

Same model throughout (Gemini 2.5 Flash). The only variable was the
architecture. `peer_to_peer` didn't fail because the model was confused; it
failed because the handoff format had no slot for `credit_hold`. The agent then
confidently did the wrong thing, having never seen the data.

→ **[Full report](studies/multi_agent_handoff/results/sweep_20260627/report.md)**

## Why it's unique

The hard part isn't running multi-agent systems — it's *attributing* their
failures. A pipeline returns a wrong answer; nothing in the output tells you
whether the agent reasoned badly or never received the input. Most harnesses
stop at pass/fail and leave you guessing.

This study is built to make that distinction mechanically:

- **A normalized trace across every architecture.** All four emit the same
  append-only JSONL schema — `llm_call`, `tool_call`, `peer_handoff`,
  `worker_finish`, `critic_review`, `revision_start` — forming a replayable
  execution DAG. The trace is the evidence, and it's committed to this repo.
- **A failure taxonomy, not a boolean.** Every run grades to exactly one of
  `task_failure` (had the data, chose wrong), `coordination_failure` (the
  architecture prevented it from seeing the data), `tool_error_unrecovered`, or
  `incomplete`.
- **Graded against real state, not an LLM judge.** Success is checked against the
  mock SQLite database plus semantic scanning of trace events.
- **A deliberately fair baseline.** The single-agent control gets *unrestricted*
  tool access, so multi-agent failures can't be dismissed as a rigged comparison.
- **The trap task is the instrument.** `task_02` gives one agent a flag the
  deciding agent needs. An architecture with a lossy boundary cannot pass it, and
  the grader can prove the field was missing at the moment of decision.

## Where

| Path | What it holds |
|---|---|
| `studies/multi_agent_handoff/core/` | Providers, agent loop, mock tools, trace logger, the 4 architectures |
| `studies/multi_agent_handoff/evals/` | Grader and the 2 eval task definitions |
| `studies/multi_agent_handoff/run_baseline.py` | One architecture, one task |
| `studies/multi_agent_handoff/run_all.py` | Multi-trial sweep |
| `studies/multi_agent_handoff/report_generator.py` | Sweep manifest → markdown report |
| `studies/multi_agent_handoff/results/sweep_20260627/` | The committed 28-run sweep: traces, summary, report |

**The four architectures:**

| Architecture | Coordination mechanism |
|---|---|
| `single_agent` | None — one ReAct loop, unrestricted tools. The control. |
| `peer_to_peer` | Two agents, partitioned tools, a **rigid fixed-format handoff string** |
| `supervisor_worker` | Supervisor delegates; workers return **free-form natural-language summaries** |
| `debate_critic` | Proposer drafts, critic cross-checks claimed vs actual tool results, forces revision |

## How to use it

Not installed by the root `pip install -e .` — that installs the arena only.

```bash
cd studies/multi_agent_handoff
pip install anthropic google-generativeai tenacity
export GEMINI_API_KEY="..."      # and/or ANTHROPIC_API_KEY
```

Run commands **from that directory** — the scripts resolve `core/` and `evals/`
relative to themselves, and write to `results/` relative to your working dir.

```bash
python run_baseline.py --provider gemini                    # one run
python run_baseline.py --architecture peer_to_peer --task task_02   # the trap
python run_all.py --providers gemini --trials 3 --sw-task02-trials 7  # full sweep
python report_generator.py results/sweep_<timestamp>.json   # regenerate report
```

To test your own system for this failure mode, the reusable pieces are the trace
schema and the grader taxonomy — emit the same events from your pipeline and the
grader will tell you whether a failure was coordination or capability.

**Details:** [study README](studies/multi_agent_handoff/README.md) ·
[Architecture](studies/multi_agent_handoff/docs/ARCHITECTURE.md) ·
[Tasks and evals](studies/multi_agent_handoff/docs/TASKS_AND_EVALS.md) ·
[Trace schema](studies/multi_agent_handoff/docs/TRACE_SCHEMA.md)

---

## Repo layout

```
agent_arena/                    the installable engine  ─┐
agent_arena/web/                the browser UI (`arena ui`)│
projects/                       example + your projects  ├─ Universal Arena
tests/                          258 engine + UI tests    │
demo/  demo.md                  local-model walkthrough ─┘

studies/multi_agent_handoff/    the frozen study (code, docs, committed sweep)

docs/                           UNIVERSAL_ARENA.md, EXAMPLE_REPORT.md, DECISIONS.md
docs/adr/                       ADRs 0001–0011, one sequence spanning both systems
```

## Documentation

- **[Universal Arena guide](docs/UNIVERSAL_ARENA.md)** — full reference for the arena
- **[Demo](demo.md)** — end-to-end walkthrough with local models and real output
- **[Sample report](docs/EXAMPLE_REPORT.md)** — what the arena produces
- **[Multi-agent study](studies/multi_agent_handoff/README.md)** — the frozen study
- **[Roadmap](docs/ROADMAP_10X.md)** — where this goes next, and what it deliberately will not become
- **[Decisions (ADRs)](docs/DECISIONS.md)** — why trace formats, retry strategy, failure injection, and the config-driven design are what they are. The **System** column says which project each decision governs.
