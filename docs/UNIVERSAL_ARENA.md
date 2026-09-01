# The Universal Arena

A config-driven harness for answering one question for *your* project: **which
model should we use, and what does that choice cost us?**

The engine knows nothing about any project. A project is a folder containing a
config file and some test cases; point the arena at it and it runs every model
against every case, scores the outputs with pluggable scorers, and ranks the
field by a weighted composite of the criteria you said mattered.

```bash
pip install -e .                                   # or: pip install agent-arena
arena evaluate --project projects/support_triage   # runs offline, no API key
```

---

## Contents

1. [The five-minute version](#the-five-minute-version)
2. [Anatomy of a project](#anatomy-of-a-project)
3. [Test-case schema](#test-case-schema)
4. [Scorers](#scorers)
5. [Models and providers](#models-and-providers)
6. [Metrics, weights and the composite](#metrics-weights-and-the-composite)
7. [Hard constraints](#hard-constraints)
8. [Cost and the model catalog](#cost-and-the-model-catalog)
9. [Hooks](#hooks)
10. [Results database](#results-database)
11. [CLI and Python API](#cli-and-python-api)
12. [Pipeline targets — evaluating a system](#pipeline-targets--evaluating-a-system)
13. [The browser UI](#the-browser-ui)
14. [Design decisions worth knowing](#design-decisions-worth-knowing)

---

## The five-minute version

```bash
arena init projects/my_project      # scaffold
# edit config.yaml (models, weights, constraints) and tests.yaml (your cases)
arena validate --project projects/my_project    # config, tests, credentials
arena evaluate --project projects/my_project --dry-run    # plan + cost estimate
arena evaluate --project projects/my_project
```

You get a console leaderboard, a Markdown report, a JSON dump, and a SQLite
database you can query across runs.

To evaluate a completely different project, copy the template, change the test
cases and the weights, and run the same command. There is no second code path.

---

## Anatomy of a project

```
projects/my_project/
  config.yaml       models, weights, constraints, budgets   ← the whole contract
  tests.yaml        your test cases (or tests.jsonl, or a tests/ folder)
  scorers/          optional — grading logic only you can write
  hooks.py          optional — touch outputs before they are graded
  results/          written by the arena: reports + arena.sqlite
```

Discovery is by convention: any `test*.{yaml,yml,json,jsonl}` beside the config
plus everything under `tests/` is picked up, and a `scorers/` folder is loaded
automatically. Override either with `tests.paths` / `scorers.paths`.

Two complete examples ship with the repo, deliberately shaped differently:

| Project | Shape | Shows off |
|---|---|---|
| [`projects/support_triage`](../projects/support_triage) | High-volume one-word classification | Cost/latency-heavy weights, an accuracy floor, per-tag breakdown |
| [`projects/doc_extraction`](../projects/doc_extraction) | Structured extraction from documents | `json_match`, a project-local scorer, a post-process hook, deployment + privacy gates |

Both run entirely offline against simulated models, so you can see a real
leaderboard before spending anything.

---

## Test-case schema

Mandatory: `input`. Almost always wanted: `reference` and `eval_type`.

```yaml
- id: refund_intent                 # stable name used in reports and the DB
  input: "My order never arrived, I want my money back."
  reference: refund                 # a list means "any of these is correct"
  eval_type: classification         # defaults to scorers.default
  context: "Reply with one word."   # per-case system prompt
  tags: [billing, easy]             # filter runs; break the report down by tag
  weight: 2                         # counts double toward accuracy
  max_tokens: 8                     # per-case generation overrides
  temperature: 0
  params: {labels: [refund, billing, spam]}   # passed to the scorer
```

* `input` may be a string or a `[{role, content}]` message list.
* Common aliases are accepted (`prompt`/`question` for `input`,
  `expected`/`answer`/`gold` for `reference`, `system` for `context`).
* Any field the schema does not recognise is kept in `metadata` rather than
  dropped, so your own bookkeeping survives the round trip.
* A file may be a bare list, or a mapping with `defaults:` (applied to every
  case in that file) and `tests:`.
* `enabled: false` or `skip: true` parks a case without deleting it.

---

## Scorers

`eval_type` selects the scorer. Built in:

| `eval_type` | Grades by |
|---|---|
| `exact_match` | Normalised string equality (case/punctuation/whitespace insensitive by default) |
| `contains` | Substring containment; `mode: any` or `all`, with partial credit |
| `regex` | Regex search, optionally comparing a capture group |
| `classification` | Which of `params.labels` the answer names |
| `numeric` | The number in the answer, within `abs_tol`/`rel_tol` |
| `json_match` | JSON-parses the answer; `mode: subset` or `exact` |
| `semantic` | Similarity above a threshold — lexical by default, or your embedding function |
| `llm_judge` | A judge model's 0–1 verdict against a rubric |
| `code_exec` | Runs the generated code against your assertions in a subprocess |
| `manual` | Records the output unscored, for human review |

Anything else goes in the project's `scorers/` folder. Three registration
styles, all equivalent:

```python
from agent_arena.scorers import Scorer, ScoreResult, scorer

class ToneScorer(Scorer):                 # 1) a Scorer subclass
    name = "tone"
    def score(self, output, reference, context):
        polite = "please" in output.lower()
        return ScoreResult(score=1.0 if polite else 0.0, passed=polite,
                           metrics={"politeness": 1.0 if polite else 0.0})

@scorer("has_citation", requires_reference=False)     # 2) a decorated function
def has_citation(output, reference, context):
    return ScoreResult(score=1.0 if "[" in output else 0.0)

SCORERS = {"tone_v2": ToneScorer}                     # 3) an explicit mapping
```

A `ScoreResult` may carry `metrics={...}`; those become project-specific
metrics you can weight in the composite by name, exactly like `accuracy`.

Two notes on the ones that surprise people:

* **`semantic` is lexical by default.** Token-set cosine over content words —
  no model, no network, and honest about being shallow. Point
  `params.embedding` at a `(text) -> list[float]` function for real embeddings.
* **`code_exec` executes model output** in a subprocess with a timeout and a
  scratch directory. That is not a sandbox. Run untrusted outputs in a
  container.

---

## Models and providers

```yaml
models:
  - claude-opus-5                     # provider inferred from the id
  - gpt-4o
  - gemini-2.5-flash

  - key: opus_low_effort              # long form: stable key + params
    model: claude-opus-5
    label: "Opus 5 (low effort)"
    params: {output_config: {effort: low}}

  - key: local_llama                  # anything LiteLLM can reach
    model: ollama/llama3.3
    provider: litellm
    api_base: http://localhost:11434
    card: {input_usd_per_mtok: 0, output_usd_per_mtok: 0, context_tokens: 131072}
```

Provider resolution: an explicit `provider:` wins; otherwise the model id's
prefix decides (`claude-*` → anthropic, `gpt-*`/`o3-*` → openai, `gemini-*` →
gemini, `mock:*` → the offline mock, `llama*`/`qwen*`/`mistral*`/`ollama/*` →
local); a bare `api_base:` also means local; any other `vendor/model` id goes
to LiteLLM.

Provider SDKs are imported lazily, so the arena installs and its whole test
suite runs with none of them present:

```bash
pip install 'agent-arena[anthropic]'    # or [openai], [gemini], [litellm], [all]
```

### Local models

Models on your own machine need **no SDK at all** — the local connector is
stdlib `urllib` speaking the OpenAI-compatible `POST /v1/chat/completions` that
Ollama, LM Studio, llama.cpp and vLLM all expose:

```yaml
models:
  - llama3.2                                        # Ollama on :11434, inferred
  - {key: qwen, model: ollama/qwen2.5-coder:7b}
  - {key: studio, model: my-finetune, api_base: http://localhost:1234/v1}
```

They are priced at `$0.00` per call — true, for marginal API cost — and satisfy
`on_prem`, `training_opt_out` and `zero_data_retention` privacy gates outright,
which is usually the whole reason to consider them. A server that is not
running, or a model that has not been pulled, is **skipped with a reason**
before the run starts rather than failing every test case:

```
! llama32   llama3.2   model 'llama3.2' is not served by http://localhost:11434/v1
                       (available: qwen2.5:7b) — try `ollama pull llama3.2`
```

See [`demo.md`](../demo.md) for a full local-model walkthrough.

A model whose API key is missing is **skipped with a note**, not failed — the
rest of the run still produces an answer.

The `mock:` provider is a deterministic offline model. It is what makes the
examples runnable without keys, and it is worth keeping in a real project as a
synthetic baseline that proves your scorers and weights behave before you
spend anything:

```yaml
- key: sim_small
  model: mock:small
  params: {mode: flaky, accuracy: 78, latency_ms: 190}
```

Modes: `oracle` (always right), `flaky` (right `accuracy`% of the time,
deterministically per test), `fixed`, `echo`, `empty`.

---

## Metrics, weights and the composite

Built-in metrics: `accuracy`, `pass_rate`, `reliability`, `cost`, `latency`,
`latency_p95`, `tokens` — plus any custom metric your scorers or hooks emit.

```yaml
metrics:
  weights:
    accuracy: 0.55
    cost: 0.25
    latency: 0.20
  cost:
    budget_usd_per_1k_calls: 2.0
  latency:
    target_ms: 800
  tie_breaker: accuracy
```

Weights are normalised, so `{5, 3, 2}` and `{0.5, 0.3, 0.2}` mean the same
thing. Each metric is scaled to `[0, 1]` where 1 is best, then combined.

Two normalisation modes:

| Mode | Behaviour | Use when |
|---|---|---|
| `minmax` (default) | Best in the field scores 1.0, worst 0.0 | You only want a ranking |
| `target` / `budget` | Absolute. Lower-is-better: the target is a **ceiling** and the score is the headroom under it (`1 - value/target`) — free scores 1.0, half the budget 0.5, at or over budget 0.0. Higher-is-better: the target is a **goal** and the score is `value/target`, capped at 1.0. | You have a real number in mind |

Giving a `budget`/`target` switches that metric to absolute mode
automatically. It matters: under `minmax`, "cheapest" wins even if every
option is unaffordable; under `budget`, a model is judged against your actual
constraint.

Units, so the numbers mean what you think: `cost` is **USD per 1,000 calls**,
`latency` is **mean milliseconds**, `accuracy` is **0–1**.

---

## Hard constraints

Some requirements are not trade-offs. A model failing one is **disqualified**,
not ranked lower — and disqualified models are excluded from the min-max
ranges, so an unusable outlier cannot distort how the real candidates compare.

```yaml
constraints:
  min_accuracy: 0.70
  max_error_rate: 0.05
  max_latency_p95_ms: 4000
  max_cost_per_1k_calls_usd: 10
  deployment:
    required_features: [structured_outputs, function_calling]
    min_context_tokens: 200000
  privacy:
    required: [dpa, training_opt_out]
```

Privacy is treated carefully on purpose. Whether a DPA is in place, whether
training opt-out applies, whether zero-data-retention is enabled — these are
properties of **your contract and platform**, not of the model, so the shipped
catalog declares almost none of them. A model with no privacy facts on its
card **fails** a privacy gate rather than passing silently, which is the safe
direction for a compliance requirement. Declare what you have verified:

```yaml
pricing:
  models:
    claude-opus-5:
      privacy: {dpa: true, training_opt_out: true}
```

---

## Cost and the model catalog

`agent_arena/connectors/model_cards.json` ships prices, context windows and
capabilities for the models the maintainers can source. **A model that is not
in the catalog gets no cost metric rather than a guessed one** — its cost
weight is redistributed across its other metrics and the report says so.
Scoring an unknown price as zero would make an unpriced model look free;
scoring it as worst would punish it for a gap in our data.

Supply your own numbers — negotiated rates, a provider we do not ship, the
current introductory pricing — and they layer over the catalog:

```yaml
pricing:
  path: pricing.yaml          # a file
  models:                     # or inline
    claude-sonnet-5: {input_usd_per_mtok: 2.0, output_usd_per_mtok: 10.0}
```

Narrow ids inherit from broader ones, so `claude-haiku-4-5-20251001` picks up
`claude-haiku-4-5`, and `mock:frontier` inherits the `mock` card while
overriding its price.

```bash
arena models --project projects/my_project     # what is priced, what is not
```

Always verify against your provider's current price list before making a
decision on cost.

---

## Hooks

```yaml
hooks:
  pre_request:  "hooks.py:add_context"
  post_process: "hooks.py:strip_pii"
  on_result:    "hooks.py:notify"
```

`post_process(output, test_case, context)` runs before scoring. Return a
string to replace the output, or a mapping to decide the verdict outright:

```python
def strip_pii(output, test_case, context):
    return EMAIL_RE.sub("[email]", output)

def check_schema(output, test_case, context):
    ok = validate(output)
    return {"output": output, "passed": ok, "score": 1.0 if ok else 0.0,
            "metrics": {"schema_errors": 0 if ok else 1}}
```

`pre_request(request, test_case, model_key)` can inject retrieved context or
few-shot examples before the call.

---

## Results database

Every call lands in SQLite (`results/arena.sqlite` by default) with the run
that produced it, so you can answer questions no single report can:

```bash
arena history --project projects/my_project                    # runs over time
arena history --project projects/my_project --model claude-opus-5   # regressions
arena history --project projects/my_project --flaky            # unstable tests
arena report  --project projects/my_project                    # re-read a run
```

Tables: `runs` (one row per sweep, with the config snapshot and git sha),
`results` (one row per call), `rankings` (the leaderboard as computed). Point
several projects at one file with `output.db` if you would rather query across
them.

---

## CLI and Python API

```bash
arena evaluate --project P [--models A B] [--trials N] [--tags t1 t2]
               [--ids case1] [--limit N] [--concurrency N]
               [--dry-run] [--json] [--fail-under 0.8]
arena validate --project P        # config, tests, scorers, credentials
arena tests    --project P        # what will run
arena models   --project P        # prices, context windows, features
arena scorers  --project P        # available eval types, built-in and local
arena report   --project P [--run-id ID]
arena history  --project P [--model K] [--flaky]
arena init     PATH
arena ui       [--projects-dir DIR] [--port 8420] [--host 127.0.0.1] [--no-browser]
```

`--fail-under` exits non-zero when the best composite falls below a threshold,
which is the hook for running the arena in CI as a model-regression gate.

```python
from agent_arena import run

result = run("projects/my_project", trials=3, tags=["smoke"])
print(result.winner.key, result.winner.composite)

for entry in result.leaderboard.ranked:
    print(entry.key, entry.raw("accuracy"), entry.raw("cost"))
```

Lower-level pieces (`ArenaRunner`, `ProjectConfig`, `ScorerRegistry`,
`PriceBook`, `ResultStore`) are all importable if you want to embed the arena
in something larger.

---

## Pipeline targets — evaluating a system

The arena's default unit is one prompt → one completion. Most shipped systems
are not that: they retrieve, plan, call tools, critique, then synthesise. A
**target** puts one of those on the same leaderboard as a plain model.

```yaml
targets:
  - key: rag_v1
    run: pipelines/rag.py:answer
  - key: rag_v2_with_critic
    run: pipelines/rag.py:answer
    params: {critic: true}          # reaches the callable as `params`

models:
  - key: single_call_baseline       # the control, in the same run
    model: claude-sonnet-5
```

`targets:` and `models:` are **one list** under two names — use whichever reads
better; a project may use both. Everything downstream is unchanged: the same
scorers grade a target, the same weights rank it, the same constraints can
disqualify it.

### The callable contract

```python
def answer(prompt):
    return "billing"
```

That is the whole minimum. The prompt arrives positionally; anything else is
optional and **you receive only what you declare**, so a target never has to
accept arguments it does not care about:

| Keyword | What it carries |
|---|---|
| `messages` | The case's input as a role/content list |
| `system` | The project's system prompt |
| `test_id`, `trial` | Which case, which repeat |
| `tags` | The case's tags |
| `reference` | The expected answer — for logging, not for cheating |
| `params` | The entry's `params:` merged with the request's |

```python
def answer(prompt, *, tags, test_id):     # gets exactly these two
    ...

def answer(prompt, **context):            # gets all of them
    ...
```

### Reporting what it cost

Return a string, or a mapping when the pipeline knows more than the arena can
see from outside:

```python
def answer(prompt):
    return {
        "output": "...",          # or "text" / "answer"
        "input_tokens": 4210,     # totalled across every internal call
        "output_tokens": 380,
        "cost_usd": 0.0092,       # real end-to-end spend for this one case
        "latency_ms": 1840.0,
        "metrics": {"agent_calls": 3, "retrieved_docs": 8},
    }
```

Two things follow, both deliberate:

- **A reported `cost_usd` is trusted over the price catalog.** The catalog
  cannot price a pipeline; the pipeline can. Report nothing and cost is left
  unmeasured rather than guessed — and its weight is redistributed, with a note
  saying so.
- **`metrics` are weightable by name**, exactly like a scorer's custom metrics.
  Put `agent_calls: 0.1` in `metrics.weights` and the leaderboard will start
  preferring architectures that use fewer agents.

### Failure handling

A target that raises fails that call, not the run — the same as a provider
error, retried per `run.retries` and then recorded. A target whose file or
function is missing is caught at **load** time by `arena validate`, and its
import is checked in preflight, so a typo costs nothing rather than failing on
the first case after other models have already been paid for.

### The worked example

`projects/pipeline_demo/` compares three architectures for one support-triage
task, fully offline:

```
  #  model              composite  accuracy  cost   latency  status
  1  single_agent       0.907      100.0%    $0.90  220ms    ranked
  -  peer_to_peer       —          27.3%     $1.80  440ms    DISQUALIFIED
  -  supervisor_worker  —          63.6%     $2.70  660ms    DISQUALIFIED

  ✗ peer_to_peer: accuracy 27.3% below the required 80.0%
  ✗ supervisor_worker: accuracy 63.6% below the required 80.0%
```

The task hides one fact — whether the account is on credit hold — that the first
stage sees and the last stage needs. `peer_to_peer` hands off a fixed-format
string with no field for it, so it loses it every time. `supervisor_worker`
hands off a free-text summary, which keeps the fact when it is prominent and
drops it when it is buried late in a long ticket — the intermittent failure that
reads like a prompt problem for weeks before anyone finds the structural cause.

This is the multi-agent study's finding, made rankable: the study proved a
coordination failure exists and is separable from a capability failure; targets
let you price it and gate on it. See
[the study](../studies/multi_agent_handoff/README.md) for the original
experiment.

---

## The browser UI

```bash
arena ui                                   # http://localhost:8420
arena ui --projects-dir ~/evals --port 8421
```

Same engine, no terminal. It exists because the person who knows the accuracy
floor and the budget is usually not the person who writes YAML, and a tool whose
answer only reaches developers is answering the wrong audience.

### What it does

| Screen | What it is for |
|---|---|
| Your evaluations | Every project folder under `--projects-dir`, with its last winner |
| New evaluation | A five-step wizard that writes `config.yaml` + `tests.yaml` |
| Evaluation | What will run, what matters, the examples, and the Run button |
| Running | Live progress plus a feed of what each model actually answered |
| Result | The verdict in sentences, the full table, and what-if sliders |
| Past runs | Every stored run and an accuracy trend per model |

### The wizard

Step one asks what job the AI is doing, in seven plain descriptions rather than
by scorer name:

| The question it asks | What it configures |
|---|---|
| Sort things into categories | `classification`, plus the label list |
| Pull specific details out of text | `json_match` |
| Answer questions | `semantic` |
| Find a specific fact | `contains` |
| Calculate a number | `numeric` |
| Write or summarise | `llm_judge` (warns that the judge costs money) |
| Match an exact answer | `exact_match` |

Each preset also carries a starting system prompt, a sensible `max_tokens`, and
default weights — a classification job starts cost-sensitive, an extraction job
starts accuracy-dominated. The output is an ordinary project folder: the CLI can
run it, and a developer can edit it by hand afterwards.

### What-if re-scoring

The one thing the UI can do that the CLI cannot. Move the priority sliders on a
finished run and the leaderboard is rebuilt **from the answers already stored**
— no model calls, no spend. It rehydrates `CallResult` rows out of SQLite and
calls the same `build_leaderboard`, so a what-if and a fresh run with those
weights cannot disagree.

This is usually where the real conversation happens: *"we said cost mattered a
quarter — if it only mattered a twentieth, would we still pick this?"*

### Plain-English layer

`agent_arena/web/language.py` holds every translation, as pure functions over
already-computed results. It invents no judgement of its own — the ranking, the
disqualifications and the caveats all come from `core/metrics.py`; this module
only re-words them.

```
0.833                        →  "83 out of 100"
$0.06/1k calls               →  "6¢ per 1,000 uses"
190 ms                       →  "190 milliseconds (instant)"
accuracy 50.0% below 70.0%   →  "It only gets 50 out of 100 right,
                                 which is below the floor you set."
```

The "too close to call" rule is enforced in the UI too: inside 0.02 composite the
verdict drops to low confidence and says so, rather than crowning a winner a
twelve-case sweep cannot support.

### Operational notes

- **Stdlib only.** `http.server` plus vanilla JS. No Flask, no npm, no CDN. It
  works on a locked-down laptop with no internet.
- **Localhost by default, and no login.** It reads and writes your project files
  and can spend against your API keys. Binding it to a non-loopback address puts
  that on your network unauthenticated — the command prints a warning if you do.
- **Guards:** project names are restricted to a safe character set and re-checked
  against the projects directory before any write; the `Host` header is
  allow-listed against DNS rebinding; static serving cannot walk out of
  `web/static/`; a second click on Run returns the in-flight job instead of
  starting a second paid run.
- **Editing limits.** The visual editors refuse to rewrite a project that spreads
  its test cases across several files or uses custom hooks, rather than
  clobbering something it does not fully model.

---

## Design decisions worth knowing

These change what the numbers mean, so they are stated rather than buried.

**Accuracy is measured over completed calls only.** Failed calls are counted
separately as `reliability`. Otherwise a model that errors on 90% of calls and
answers the remaining 10% correctly would report 100% accuracy. If you do not
weight `reliability` and errors occurred, the report tells you.

**An unmeasurable metric redistributes its weight** instead of scoring zero —
see [Cost](#cost-and-the-model-catalog).

**Disqualified models are excluded from min-max ranges.** A model that fails a
hard constraint should not change how the qualifying models compare to each
other.

**A metric everyone ties on scores 1.0 for everyone.** It carries no
information, so it should not swing the composite in either direction.

**Small margins are called out.** When the top two are within 0.02, the report
says so and suggests more trials — a leaderboard implies more precision than a
12-case sweep can support.

**The mock provider is deterministic** per `(model, test, trial)`, so demo
runs, tests, and CI are reproducible.

---

## Relationship to the multi-agent handoff study

This repo also contains the original Agent Arena: a study of how *multi-agent
architectures* lose information at coordination boundaries, now at
[`studies/multi_agent_handoff/`](../studies/multi_agent_handoff/). The two are
independent and answer different questions:

| | Question | Varies | Holds fixed |
|---|---|---|---|
| Multi-agent study | Does decomposing a task across agents introduce failures? | The architecture | The model |
| Universal arena | Which model should this project use? | The model | The task |

They share a philosophy — structured evidence over vibes — but no code. The
universal arena is additive; nothing in the original harness changed. The study
is complete and frozen, and is not part of the installable package — it keeps
its own dependencies and its own [README](../studies/multi_agent_handoff/README.md).
