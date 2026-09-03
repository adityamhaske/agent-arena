# Running evaluations

## Always validate first

```bash
arena validate --project projects/my_project
```

Checks config, test files and credentials, and exits non-zero on a problem. It
takes a second and catches the mistakes that would otherwise surface after a
partial spend.

## Then plan

```bash
arena evaluate --project projects/my_project --dry-run
```

Prints the full matrix and a cost estimate, and calls nothing. Do this before any
first paid run — `models × cases × trials` grows faster than people expect. Four
models, 50 cases and 3 trials is 600 calls.

## Preflight and skipping

Before spending, the runner asks each model whether it can run. A model whose
credential is missing is **skipped, not failed**:

```text
  skipping opus_5: ANTHROPIC_API_KEY is not set
```

The run continues without it, and the model appears in the leaderboard with
status `no_data` and the skip reason. Silently omitting it would make a
four-model comparison look like a three-model one.

If *every* model would be skipped, the run raises instead — an empty leaderboard
is not an answer:

```text
every model would be skipped, so there is nothing to run: opus_5 (ANTHROPIC_API_KEY is not set).
Export the missing API key(s), or add a `mock:` model to compare against.
```

**This is the failure mode to watch in CI.** A misconfigured secret produces a
green build that evaluated only your mock models. `arena validate` fails on
missing credentials; put it before `evaluate`.

## Trials versus cases

| Add | To measure |
|---|---|
| More **cases** | Whether the model handles your task — improves generalisation |
| More **trials** | How *consistently* it does — improves variance estimates |

Cases are usually the better investment. Ten cases run three times tells you
about consistency on ten situations; thirty cases run once tells you about thirty
situations. When the leaderboard says two models are too close to call, it almost
always means add cases.

Set `temperature: 0` and trials still vary, because providers are not fully
deterministic. That variance is real and worth knowing.

## Concurrency

```yaml
run:
  concurrency: 8
```

Default 4. The right value is the largest your provider tolerates without rate
limiting — **raising it past that makes a run slower**, because every rejected
call becomes a retry with backoff. See [performance.md](performance.md).

Local models are usually limited by your hardware. High concurrency against a
single GPU queues rather than parallelising.

## Timeouts and retries

```yaml
run:
  timeout_s: 120.0
  retries: 2
  retry_backoff_s: 2.0
```

Retries are classified: a 401, 403, 400, 404 or 422 fails immediately rather than
sleeping through attempts it cannot fix. 429s and 5xx retry with full jitter, and
a `Retry-After` header is honoured when the provider sends one.

Raise `timeout_s` for large local models or long generations; the default assumes
a hosted model answering promptly.

## Filtering a run

```bash
arena evaluate --project p --tags hard              # only hard cases
arena evaluate --project p --exclude-tags slow
arena evaluate --project p --ids case_1 case_2      # specific cases
arena evaluate --project p --limit 20               # cap the count
arena evaluate --project p --models sim_small       # one model
```

Iterating on a scorer? Run one mock model over a handful of cases. It is free and
instant.

## Reading progress

```text
··x······xx···x···xxxxxx···xxxxx······x··xx· 144/144
```

| Mark | Means |
|---|---|
| `·` | Passed |
| `x` | Ran, scored as incorrect |
| `!` | Errored |
| `?` | Other status |

A wall of `x` early usually means a scorer misconfiguration, not a bad model —
stop and check with `--limit 5` before spending the rest.

## Interruption

Ctrl-C exits 130. The run is closed out as `aborted` with its partial results
attached, so the database never holds a row stuck at `running`.

There is no resume yet: an interrupted run starts over. See
[../roadmap/status.md](../roadmap/status.md).

## After the run

```bash
arena report  --project p                 # re-show the latest
arena report  --project p --run-id <id>   # a specific run
arena history --project p                 # runs over time
arena history --project p --flaky         # unstable cases
```
