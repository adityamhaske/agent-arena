# Troubleshooting

Symptoms, with the real messages the code emits.

## Nothing ran

### "every model would be skipped, so there is nothing to run"

```text
every model would be skipped, so there is nothing to run: opus_5 (ANTHROPIC_API_KEY is not set).
Export the missing API key(s), or add a `mock:` model to compare against.
```

**Cause.** No model has usable credentials.

**Fix.** Export the key, or add a `mock:` model so the project runs offline.

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
arena validate --project projects/my_project
```

### Some models silently missing from the leaderboard

They are not missing — they are there with status `no_data` and a skip reason. A
model whose key is absent is skipped, not failed, and the run continues.

**In CI this is the dangerous one:** a misconfigured secret gives a green build
that evaluated only your mock models. Put `arena validate` before `arena evaluate`
— it fails on missing credentials.

## Config problems

### "config must list at least one entry under 'models' (or 'targets')"

The file parsed but has no competitors. Note `models:` and `targets:` are the
same list under two names.

### "No config file in \<path\>. Expected one of: ..."

**Fix.** `--project` must point at a folder containing `config.yaml` (or `.yml`,
`.json`, `arena.yaml`, `arena.json`), or directly at a config file.

### "duplicate model key 'x'; give one of them an explicit 'key'"

Two entries resolved to the same key — usually the same model id twice, which is
exactly what you do when comparing two configurations of one model.

```yaml
models:
  - {key: gpt5_cold, model: gpt-5, params: {temperature: 0}}
  - {key: gpt5_warm, model: gpt-5, params: {temperature: 1}}
```

### "metrics.\<metric\>.normalize is 'target' but no target/budget was given"

`target` and `budget` modes need a reference point.

```yaml
metrics:
  latency: {target_ms: 800}
  cost:    {budget_usd_per_1k_calls: 2.0}
```

### "unknown model(s): x. Available: ..."

`--models` named a key that is not in the config. It lists what is.

### "duplicate provider id 'x'"

Two entries in `providers:` share an `id`.

## Model routing

### "cannot infer a provider for model 'x'"

The id matches no known prefix. The message shows the YAML that fixes it:

```yaml
models:
  - model: some-exotic-model
    provider: litellm          # or anthropic | openai | gemini | local | mock
```

An explicit `api_base` also resolves it — giving a URL means it is an
OpenAI-compatible server.

### "the 'anthropic' provider needs the 'anthropic' package"

```bash
pip install 'agent-arena[anthropic]'
```

Provider SDKs are optional and import lazily, so this is expected the first time
you call a new vendor.

### "model 'x': run target does not exist"

A `run:` target points at a file that is not there. The path resolves relative to
the project folder, not your working directory.

```yaml
targets:
  - key: rag
    run: pipelines/rag.py:answer      # projects/my_project/pipelines/rag.py
```

Format must be `path/to/file.py:function`.

## Scorers

### "classification scorer needs a 'labels' list"

```yaml
scorers:
  options:
    classification:
      labels: [billing, technical, account, other]
```

### "llm_judge needs a judge model"

```yaml
judge:
  model: claude-sonnet-5
```

### "code_exec needs assertions — put them in the test case's `reference`"

`code_exec` runs generated code against assertions you supply as the reference.

### "exact_match got an empty list of acceptable answers"

A case has an empty list reference. Give at least one acceptable answer.

### Everything scores zero

Usually a scorer misconfiguration, not a bad model. Check one case:

```bash
arena evaluate --project p --models sim_small --limit 1
```

Then read `reason` in the report. Common causes: labels that do not match the
model's wording, a `json_match` reference against output wrapped in a markdown
fence (strip it in `post_process`), or `exact_match` where the model adds a
preamble.

## Cost

### No cost column at all

**Cause.** At least one completed call had no price, so cost is nulled for the
whole run. This is deliberate — a mean over the priced subset would be a
fabricated number.

The leaderboard warns and names the unpriced models.

**Fix.** Add a `card:` override, a project pricing file, or return `cost_usd`
from a `run:` target.

```yaml
models:
  - key: my_model
    model: some-model
    card: {input_usd_per_mtok: 3.0, output_usd_per_mtok: 15.0}
```

The catalog will not invent a price for you; supplying one is your deliberate act.

## The UI

### "Could not start the UI on 127.0.0.1:8420"

```text
Another program is probably using that port. Try `arena ui --port 8421`.
```

### "This server only answers requests from localhost"

A 403 from the Host allow-list, which blocks DNS rebinding. If you deliberately
bound elsewhere, pass the same value to `--host` so it joins the allow-list.

### A run cannot be stopped from the browser

Correct — the runner has no cooperative cancellation check yet. Ctrl-C in the
terminal running `arena ui` stops the process; the run is closed out as aborted
with partial results kept. See [../roadmap/status.md](../roadmap/status.md).

## Local models

| Symptom | Cause | Fix |
|---|---|---|
| Connection refused | Runtime not running | `ollama serve` |
| 404 from the endpoint | Wrong base path | `api_base` ends at `/v1` |
| Model not found | Not pulled | `ollama pull <model>` |
| Timeouts | Large model, small timeout | Raise `run.timeout_s` |
| Very slow first call | Model loading | Warm it before timing |

## Rate limits and flakiness

### Many retries, a slow run

Concurrency above what the provider allows. Every rejected call becomes a retry
with backoff, so raising it further makes things worse.

```yaml
run:
  concurrency: 4
```

### A 401 fails immediately

Correct behaviour. A bad key cannot be fixed by retrying, so it is classified
terminal and fails on the first attempt rather than sleeping through three.

### Results differ between runs

Expected. Providers are not fully deterministic even at `temperature: 0`.

```bash
arena history --project p --flaky
```

A case that flips repeatedly is either genuinely ambiguous or badly specified,
and either way it is adding noise to your ranking.

## Getting more detail

```bash
arena validate --project p          # config, tests, credentials
arena tests    --project p          # what will actually run
arena models   --project p          # cards, prices, inferred providers
arena evaluate --project p --dry-run
arena ui --verbose                  # log every HTTP request
```

An `ArenaError` prints as `error: <message>` and exits 1. Those messages are
written to name the fix — read the whole thing before searching.
