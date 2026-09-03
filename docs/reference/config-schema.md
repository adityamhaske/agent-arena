# Config schema

Complete reference for `config.yaml` and `tests.yaml`. Blocks marked **v2** are
optional additions; omitting them preserves v1 behaviour exactly.

## `config.yaml`

### Identity

| Field | Type | Default | Means |
|---|---|---|---|
| `project` / `name` | string | folder name | Project name, used as the database key |
| `description` | string | `""` | Free text |

### `models:` / `targets:`

One list under two names. Every entry:

| Field | Type | Means |
|---|---|---|
| `key` / `id` | string | Unique name in reports. Defaults to the model id |
| `model` / `id` / `name` | string | Provider's model identifier |
| `run` / `target` / `callable` | string | `file.py:function` — a pipeline target instead of a model |
| `provider` | string | Explicit provider, or **v2** a `providers[].id` |
| `params` | map | Extra generation kwargs, merged over `defaults` |
| `api_key_env` | string | Environment variable holding this model's key |
| `api_base` / `base_url` | string | Endpoint, for OpenAI-compatible servers |
| `label` | string | Display name |
| `card` | map | Per-model price/capability overrides |
| `enabled` | bool | Default `true` |

A shorthand string is expanded: `models: [claude-opus-5]` means
`{key: claude-opus-5, model: claude-opus-5}`.

### `providers:` — **v2**

Named connection profiles. Optional; empty by default.

| Field | Type | Means |
|---|---|---|
| `id` | string | **Required.** Referenced by a model's `provider:` |
| `kind` | string | **Required.** `anthropic`, `openai`, `gemini`, `litellm`, `local`, `ollama`, `lmstudio`, `mock`, `openai_compatible` |
| `base_url` | string | Endpoint |
| `api_key` / `api_key_ref` | string | A secret reference — never a literal |
| `headers` | map | Extra HTTP headers |
| `timeout_s` | float | Request timeout |
| `verify_tls` | bool or path | `false` disables verification; a path loads a CA bundle |
| `proxy` | string | Proxy URL |
| `model_prefix` | string | Prepended to the model id on the way out |
| `rate_limit` | map | `rpm`, `tpm`, `concurrency` |
| `retry` | map | `attempts`, `backoff_s`, `jitter`, `respect_retry_after` |
| `params` | map | Defaults for every model using this profile |

Parses and resolves today; **the runner does not yet route through a profile**.

### `budgets:` — **v2**

| Field | Type | Default | Means |
|---|---|---|---|
| `max_run_usd` | float | none | Cap for the whole run |
| `max_model_usd` | float | none | Cap per model |
| `confirm_above_usd` | float | none | Ask before starting above this estimate |
| `on_exceed` | string | `stop` | `stop` or `warn` |

Parses and validates today; **the runner does not yet enforce a cap**.

### `defaults:`

Applied to every model. Typically `system`, `max_tokens`, `temperature`.

### `run:`

| Field | Type | Default |
|---|---|---|
| `trials` | int | `1` |
| `concurrency` | int | `4` |
| `timeout_s` | float | `120.0` |
| `retries` | int | `2` |
| `retry_backoff_s` | float | `2.0` |
| `fail_fast` | bool | `false` |
| `seed` | int | none |

### `metrics:`

| Field | Type | Default | Means |
|---|---|---|---|
| `weights` | map | — | Metric name → weight. Normalized to sum to 1 |
| `directions` | map | — | `higher` or `lower` is better, per metric |
| `normalize` | map | — | `minmax`, `target`, `budget`, `raw`, per metric |
| `targets` | map | — | Ceilings for `target` mode, e.g. `latency.target_ms` |
| `tie_breaker` | string | `accuracy` | Orders equal composites |
| `cost.budget_usd_per_1k_calls` | float | — | Budget for `budget` mode |

Any metric a scorer or connector emits can be weighted by name.

### `constraints:`

A violation disqualifies. All optional.

| Field | Type | Means |
|---|---|---|
| `min_accuracy` | float | Accuracy floor |
| `max_latency_p95_ms` | float | p95 ceiling |
| `max_cost_per_1k_calls_usd` | float | Cost ceiling |
| `max_error_rate` | float | Error-rate ceiling |
| `min_context_tokens` | int | Minimum context window |
| `required_features` | list | e.g. `tool_use`, `json_mode` |
| `privacy_required` | list | e.g. `zero_retention` |
| `allow_unknown_card` | bool | Default `true` — a model with no card passes feature/privacy checks |

### `tests:`

A list of paths, or a map:

| Field | Means |
|---|---|
| `paths` | Test file paths |
| `tags` / `exclude_tags` / `ids` / `limit` | Filters applied at load |

### `scorers:`

| Field | Means |
|---|---|
| `default` | Eval type when a case does not name one. Default `exact_match` |
| `options` | Per-type options, keyed by eval type |
| `paths` | Extra directories to load custom scorers from |

### `judge:`

Model and prompt for `llm_judge`. Needs `model` at minimum.

### `hooks:`

| Field | Means |
|---|---|
| `pre_request` | `file.py:function`, called before the model |
| `post_process` | `file.py:function`, called before grading |

### `pricing:`

| Field | Means |
|---|---|
| `path` | A pricing file merged over the shipped catalog |
| `models` | Inline per-model overrides |

A bare string is shorthand for `{path: ...}`.

### `output:`

| Field | Default | Means |
|---|---|---|
| `dir` | `results` | Where reports and the database go |
| `db` | `<dir>/arena.sqlite` | Database path |
| `formats` | `[markdown, json]` | Report formats |

## `tests.yaml`

```yaml
tests:
  - id: double_charge
    input: "I was charged twice for the same order this month."
    reference: billing
    tags: [billing, easy]
    weight: 1.0
```

| Field | Type | Means |
|---|---|---|
| `id` | string | Stable identifier. A database key — renaming breaks its history |
| `input` | string | The prompt |
| `reference` | any | Expected value; shape depends on the eval type |
| `eval_type` | string | Per-case override of `scorers.default` |
| `tags` | list | For filtering and per-tag reporting |
| `weight` | float | Relative importance in the accuracy aggregate |

## A complete example

```yaml
project: support_triage
description: Route inbound support tickets to the right queue.

models:
  - key: sim_small
    model: mock:small
    card: {input_usd_per_mtok: 1, output_usd_per_mtok: 5}
  - key: opus_5
    model: claude-opus-5        # skipped, not failed, if the key is missing

defaults:
  system: "Reply with exactly one label."
  max_tokens: 8
  temperature: 0

run:
  trials: 3
  concurrency: 8
  timeout_s: 30

metrics:
  weights: {accuracy: 0.55, cost: 0.25, latency: 0.20}
  cost:    {budget_usd_per_1k_calls: 2.0}
  latency: {target_ms: 800}

constraints:
  min_accuracy: 0.70
  max_latency_p95_ms: 4000

scorers:
  default: classification
  options:
    classification:
      labels: [billing, technical, account, other]
```
