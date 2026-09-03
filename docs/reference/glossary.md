# Glossary

Terms this project uses in a specific way.

**Arena** — the evaluation engine. Also `agent_arena`, the Python package.

**Project** — a folder containing `config.yaml` and `tests.yaml`, and optionally
`scorers/` and `hooks.py`. The unit of "a thing being evaluated". Not code.

**Model** — one competitor. An entry under `models:` with a key, a model id and
optional per-model settings.

**Target** — the same thing as a model, under a name that reads better for
pipelines. An entry with `run:` pointing at a Python callable, so a whole
multi-agent system competes on the same leaderboard as a single model call.
`models:` and `targets:` are one list.

**Key** (of a model) — the unique name an entry appears under in reports. Defaults
to the model id. Two entries using the same model id need distinct keys.

**Case** — one test: an input, a reference, and optionally an eval type, tags and
a weight. Lives in `tests.yaml`.

**Trial** — one repetition of one case against one model. `run.trials: 3` runs
every case three times per model, which is how you see variance.

**Run** — one execution of the whole matrix: models × cases × trials. Has a run
id, a row in `runs`, and a folder under `results/`.

**Run id** — `run_<timestamp>_<random>`. Also the results subdirectory name.

**Scorer** / **eval type** — the thing that turns one output into a number in
[0, 1]. Ten builtins, plus any Python file in the project's `scorers/`.

**Judge** — a model used *by* a scorer to grade, in `llm_judge`. Configured under
`judge:`.

**Hook** — a project-defined function that touches data in flight.
`pre_request` before the call; `post_process` after the output and before grading.

**Connector** — the adapter for one provider. Takes a `GenerationRequest`,
returns a `GenerationResult`.

**Provider** — a vendor or runtime: anthropic, openai, gemini, litellm, local,
mock. Inferred from the model id when not stated.

**Provider profile** — a named entry under `providers:` with a base URL,
credential reference, headers, TLS settings and rate limits. Lets two API keys
for the same vendor compete in one run. (Parses today; the runner does not yet
route through one.)

**Model card** — price, context window, features and privacy properties for a
model. From `model_cards.json`, a project pricing file, or a `card:` override.

**Price book** — the resolved catalog of model cards for a run.

**Raw metric** — an aggregate in its natural unit: accuracy as a fraction, cost
in USD per 1,000 calls, latency in milliseconds.

**Normalization mode** — how a raw metric becomes 0–1. `minmax` (relative to this
run), `target` (against a ceiling), `budget` (against a budget), `raw` (already
0–1).

**Composite** — the weighted sum of normalized metrics. The number the
leaderboard sorts by.

**Weights** — how much you care about each metric, under `metrics.weights`.
Normalized to sum to 1.

**Constraint** — a hard, non-negotiable requirement under `constraints:`. Failing
one disqualifies.

**Disqualified** — a model that violated a constraint. It gets **no rank** and
the reason is printed, rather than being ranked low. A leaderboard that ranks an
unusable model fourth implies the ordering is meaningful all the way down.

**Skipped** — a model that could not run, usually a missing credential. Reported
with status `no_data` and the reason; the run continues without it. Distinct from
failed.

**Resolution** — whether a sweep has enough evidence to separate two models. When
the top two are inside the noise floor, the leaderboard says so instead of
crowning a winner.

**What-if** — re-ranking stored results under different weights, with no new API
calls. Runs the real `build_leaderboard`, so it can never disagree with a fresh
run.

**Preflight** — the check before spending that decides which models can run.

**Secret reference** — `${env:...}`, `${keyring:...}`, `${file:...}` or
`${cmd:...}` in place of a literal credential.

**Secret** — the wrapper type whose `repr` and `str` are `***`. `.reveal()` is
the only way to the value.

**Coordination failure** — from the multi-agent study: a wrong answer caused by
the architecture never delivering the data to the agent that needed it.
Distinct from **task failure**, where the agent had the data and reasoned badly.
The distinction is the study's finding.
