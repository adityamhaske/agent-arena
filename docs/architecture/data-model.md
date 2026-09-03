# Data model

Two schemas matter: the SQLite database every run lands in, and the
`config.yaml` contract a project is written against.

## SQLite

One database per project, at `results/arena.sqlite` by default (`output.db`
overrides it). Created on first use; `CREATE TABLE IF NOT EXISTS` throughout, so
opening an existing database never destroys anything.

### `runs`

One row per evaluation.

| Column | Type | Meaning |
|---|---|---|
| `run_id` | TEXT PK | `run_<timestamp>_<random>`, also the results subdirectory name |
| `project` | TEXT | Project name from config, so one database can hold several |
| `started_at` / `finished_at` | TEXT | UTC ISO-8601 |
| `status` | TEXT | `running`, `complete`, or `aborted` |
| `arena_version` | TEXT | Which version produced this row |
| `git_sha` | TEXT | Working-tree SHA at run time, when the project is in a repo |
| `label` | TEXT | Human label for the run |
| `n_models` / `n_tests` / `n_results` | INTEGER | Planned and actual counts |
| `winner` | TEXT | Model key of the top-ranked entry |
| `total_cost_usd` | REAL | Sum of priced calls |
| `weights_json` | TEXT | The normalized weights used, so a stored run can be re-scored |
| `models_json` | TEXT | Model keys that actually ran |
| `config_json` | TEXT | Full config snapshot — what makes a run reproducible |
| `notes_json` | TEXT | Free-form |

`arena_version` and `git_sha` exist so a leaderboard from three months ago can be
attributed. `config_json` is the reason a stored run can be re-scored under
different weights without spending anything, which is what the UI's what-if
sliders do.

### `results`

One row per model × case × trial. This is the table everything else is derived
from.

| Column | Type | Meaning |
|---|---|---|
| `id` | INTEGER PK | Autoincrement |
| `run_id` | TEXT FK | → `runs.run_id` |
| `project`, `model_key`, `model`, `provider` | TEXT | What ran |
| `test_id`, `trial` | TEXT, INTEGER | Which case, which repetition |
| `eval_type` | TEXT | Scorer used |
| `status` | TEXT | `ok`, `error`, `skipped` |
| `score` | REAL | 0–1 from the scorer |
| `passed` | INTEGER | Boolean verdict, may be null for unscored types |
| `output`, `reference`, `reason` | TEXT | What the model said, what was expected, why it scored that way |
| `latency_ms` | REAL | Wall clock for the call |
| `input_tokens`, `output_tokens` | INTEGER | Usage as the provider reported it |
| `cost_usd` | REAL | Null when the model has no sourced price |
| `attempts` | INTEGER | How many tries the call took |
| `error` | TEXT | `TypeName: message` when status is `error` |
| `tags` | TEXT | Case tags, for slicing |
| `metrics_json`, `detail_json` | TEXT | Scorer-emitted numbers and scorer-specific detail |
| `created_at` | TEXT | UTC ISO-8601 |

`output` is truncated at 20,000 characters. A run that stored full outputs from a
long-context model would grow the database faster than the results justify.

### `rankings`

The leaderboard, persisted so `arena report --run-id` does not have to recompute.

| Column | Type | Meaning |
|---|---|---|
| `run_id`, `model_key` | TEXT | Composite primary key |
| `model` | TEXT | Model id |
| `rank` | INTEGER | Null when disqualified — an unusable model has no rank |
| `status` | TEXT | `ranked`, `DISQUALIFIED`, `no_data` |
| `composite` | REAL | The weighted score |
| `metrics_json`, `stats_json` | TEXT | Normalized metrics and raw aggregates |
| `failures`, `warnings` | TEXT | Constraint violations and resolution notes |

### Indexes

```sql
idx_results_run    ON results(run_id)              -- fetch one run's results
idx_results_model  ON results(project, model_key)  -- a model's history across runs
idx_results_test   ON results(project, test_id)    -- one case across models and runs
idx_runs_project   ON runs(project, started_at)    -- run history, newest first
```

Each maps to a query the tool actually issues: rendering a report, plotting a
model's trend, finding flaky cases, and listing history.

## `config.yaml`

The whole contract. Every block is optional except `models`/`targets`.

| Block | Purpose |
|---|---|
| `project`, `description` | Identity |
| `models` / `targets` | What competes. One list; two names because "targets" reads better for pipelines |
| `providers` | Named connection profiles (v2, optional) |
| `budgets` | Spend caps (v2, optional) |
| `defaults` | System prompt, `max_tokens`, `temperature` applied to every model |
| `run` | `trials`, `concurrency`, `timeout_s`, `retries`, `retry_backoff_s`, `fail_fast`, `seed` |
| `metrics` | `weights`, `directions`, `normalize`, `targets`, `tie_breaker` |
| `constraints` | Hard gates that disqualify |
| `tests` | Paths to case files, plus tag/id/limit filters |
| `scorers` | Default eval type, options per type, extra scorer paths |
| `judge` | Model and prompt for `llm_judge` |
| `hooks` | Pre-request and post-result hook functions |
| `pricing` | A price file path and per-model overrides |
| `output` | `dir`, `db`, `formats` |

Defaults, read from the dataclasses:

| Setting | Default |
|---|---|
| `run.trials` | 1 |
| `run.concurrency` | 4 |
| `run.timeout_s` | 120.0 |
| `run.retries` | 2 |
| `run.retry_backoff_s` | 2.0 |
| `run.fail_fast` | false |
| `metrics.tie_breaker` | `accuracy` |
| `constraints.allow_unknown_card` | true |
| `budgets.on_exceed` | `stop` |

Full field-by-field reference: [../reference/config-schema.md](../reference/config-schema.md).

## `tests.yaml`

```yaml
tests:
  - id: double_charge
    input: "I was charged twice for the same order this month."
    reference: billing
    tags: [billing, easy]
```

| Field | Meaning |
|---|---|
| `id` | Stable identifier. Used as a database key, so renaming one breaks its history |
| `input` | The prompt |
| `reference` | Expected value; its shape depends on the eval type |
| `eval_type` | Per-case override of `scorers.default` |
| `tags` | For `--tags` / `--exclude-tags` filtering and per-tag reporting |
| `weight` | Relative importance in the accuracy aggregate |

## Compatibility

`providers:` and `budgets:` are v2 additions. Both default to empty, and
`ProjectConfig.provider_for()` returns `None` for a bare vendor kind, so v1
routing is untouched. A config written before either block existed loads and
behaves identically — asserted for all four example projects in
`tests/test_config_providers.py`. That is invariant 9 in
[../../AGENTS.md](../../AGENTS.md).
