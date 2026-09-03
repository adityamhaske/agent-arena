# System design

## The problem

Most model comparisons answer someone else's question. MMLU, LMArena and a
vendor's own chart tell you how a model performs on a task you did not choose,
aggregated over criteria you did not pick. That is close to useless for a
shipping decision, because your accuracy floor, your latency budget and your
price ceiling are yours.

Agent Arena inverts that. It knows nothing about any task. You describe the task
and what "best" means to you; it runs the comparison and defends the answer.

## Three design commitments

Everything else follows from these.

### 1. A project is a folder, not code

A project is `config.yaml` plus `tests.yaml`. To evaluate something completely
different, copy the template and change the files. There is no second code path
and no plugin system.

This is the decision that makes the tool universal. The runner never learns what
a support ticket is, or what a currency amount is; it learns that there are
models, cases, a scorer name and a set of weights. Domain knowledge lives in the
project folder — in the test cases, in the scorer options, and optionally in a
`scorers/*.py` file the project owns.

The cost is real: a project cannot express a workflow the config schema has no
word for. The escape hatch is a `run:` target ([scoring.md](scoring.md)), which
puts an arbitrary Python callable on the leaderboard beside a plain model.

### 2. Never fabricate a number

A model with no sourced price gets **no** cost metric rather than an estimated
one. A sweep that cannot separate its top two says so instead of crowning a
winner. A model that fails a hard constraint is `DISQUALIFIED` with the reason
printed, not ranked fourth.

The last one matters most. A leaderboard that ranks an unusable model below three
usable ones is lying by omission: it implies the ordering is meaningful all the
way down. Disqualification changes the shape of the answer, which is what an
accuracy floor actually means.

This commitment has a visible consequence worth understanding: because cost is
nulled for the whole run unless *every* completed call was priced, adding one
unpriced model removes the cost axis for all of them. That is deliberate — a
composite that silently weights cost across a partial set would be a fabricated
number.

### 3. The engine is stdlib-only

PyYAML is the single runtime dependency, and even that is optional — JSON config
works without it. Every provider SDK imports lazily, inside the method that needs
it, so `pip install agent-arena` pulls in nothing you did not ask for and the
whole test suite runs with no provider SDK present.

The reasons are practical: installation is instant, the tool works on a
locked-down machine, the supply-chain surface is near zero, and there is no
transitive CVE treadmill. See [../security/dependency-policy.md](../security/dependency-policy.md).

## The run lifecycle

What happens between `arena evaluate --project p` and a row in SQLite.

```text
  1  load_config(path)                    core/config.py
     └─ parse config.yaml → ProjectConfig, validate, resolve paths

  2  load_test_cases(discover_test_files) core/testcase.py
     └─ tests.yaml → [TestCase], apply tag/id/limit filters

  3  ArenaRunner.preflight()              core/runner.py
     └─ for each model: can it run? missing key → SKIPPED, not failed

  4  plan the matrix                      core/runner.py
     └─ runnable models × cases × trials  →  N jobs

  5  ThreadPoolExecutor(run.concurrency)
     └─ each job: connector.generate() → score → CallResult
        · retries via core/retry.py (terminal vs retryable, jitter, Retry-After)
        · hooks.apply_post_process before grading
        · store.record_result() as each completes
        · progress callback emits call_complete

  6  build_leaderboard()                  core/metrics.py
     └─ aggregate raw metrics → normalize → weight → composite
        → apply constraints → DISQUALIFIED or ranked

  7  store.finish_run() + report          core/store.py, core/report.py
     └─ rankings persisted; markdown/JSON written to results/
```

### Following one call

`arena evaluate --project projects/support_triage` with `trials: 3`:

1. `cli.cmd_evaluate` builds an overrides dict from the flags and calls
   `ArenaRunner.from_project`, which calls `load_config`.
2. `ProjectConfig.from_dict` parses each entry under `models:` and `targets:`
   into a `ModelSpec` via `ModelSpec.parse`, raising `ConfigError` with the
   position on a bad field.
3. `preflight()` asks `connectors.registry.requires_api_key` what credential each
   model needs. A model whose key is absent is recorded in `skipped` — the run
   continues without it. This is why a missing `OPENAI_API_KEY` does not fail a
   run that also contains mock models.
4. `store.start_run` inserts a row into `runs` with the config snapshot, the
   arena version and the git SHA, and returns a run id.
5. For each `(spec, case, trial)`, `_execute` builds a `GenerationRequest`,
   calls `_generate_with_retries`, and hands the text to the scorer resolved from
   `case.eval_type`.
6. Cost comes from `generation.cost_usd` when the connector reported its own
   spend — a pipeline target knows its real end-to-end cost and the catalog
   cannot — otherwise from `price_book.get(model).cost_usd(...)`.
7. `build_leaderboard` aggregates every `CallResult` by model key, normalizes
   each metric, applies the weights, and gates on `constraints:`.
8. `finish_run` writes the rankings, and `core/report.py` renders markdown and
   JSON into `results/<run_id>/`.

## Extension points

| You want to | Do this | Where |
|---|---|---|
| Grade something the builtins cannot | Drop a `Scorer` subclass in the project's `scorers/` | [scoring.md](scoring.md) |
| Touch outputs before grading | `hooks.py` in the project folder | [scoring.md](scoring.md) |
| Compare a whole pipeline, not a model | A `run:` target pointing at a callable | [../guides/comparing-pipelines.md](../guides/comparing-pipelines.md) |
| Add a provider the arena cannot reach | `provider: litellm`, or a new `Connector` | [connectors.md](connectors.md) |
| Price a model the catalog omits | A `card:` override or a project pricing file | [connectors.md](connectors.md) |
| Weight a number a scorer emits | Name it in `metrics.weights` | [metrics.md](metrics.md) |

## Tensions the code actually resolves

**Stdlib-only versus convenience.** The web UI would be shorter with a
framework, and the `.env` parser and the OS-keyring integration would be a
one-line dependency each. They are hand-written instead. The trade is worth it
only because the surface is small; a project that needed HTTP/2 or async
streaming would have to revisit it honestly rather than adding "just one".

**Honesty versus a clean single number.** A composite score is what makes a
leaderboard sortable, and it is also the thing most likely to mislead. The
resolution guard, the disqualification path and the null-cost rule all exist to
keep the composite from claiming more than the evidence supports.

**Config-driven versus a plugin system.** A folder is easier to write, review
and share than a plugin. The limit is that the schema has to name a capability
before a project can use it, which is why `providers:` and `budgets:` were added
to the schema rather than exposed as hooks.
