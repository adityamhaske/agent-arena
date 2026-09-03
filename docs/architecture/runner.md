# The runner

`agent_arena/core/runner.py` — execution, concurrency, and failure handling.

## The matrix

A run is the cross product of runnable models, test cases and trials:

```text
planned = len(runnable_models) × len(test_cases) × run.trials
```

Every cell is one `CallResult`. With 4 models, 12 cases and 3 trials that is 144
calls, and the wall clock is governed by `run.concurrency` (default 4) and
provider latency, not by the total.

## Preflight

Before anything is spent, `preflight()` asks each model whether it can run.
A model whose credential is missing is **skipped, not failed**:

```text
runnable = [s for s in config.enabled_models if s.key not in skipped]
```

This is why a config containing both `claude-opus-5` and `mock:small` still
produces a leaderboard on a machine with no API key — the mock model runs and the
Claude entry is reported as skipped with the reason. A run where *every* model
would be skipped raises `ConfigError` instead, because an empty leaderboard is
not a useful answer.

Skipped models still appear in the leaderboard, with status `no_data` and the
skip reason as their only failure line. Silently omitting them would make a
four-model comparison look like a two-model one.

## Concurrency

`ThreadPoolExecutor(max_workers=run.concurrency)`. Threads rather than asyncio,
because the work is IO-bound on provider HTTP and every provider SDK is
synchronous — an async runner would need an async client per vendor, which
collides with the lazy-import rule.

Results are consumed with `as_completed`, so a slow model does not block faster
ones from recording. Each completion writes to the store immediately and emits a
`call_complete` progress event, which is what lets the CLI print a live progress
line and the browser poll a running job.

### Thread safety

Most state is per-call and needs no coordination. Two things do not:

- **The judge connector.** `llm_judge` scorers call `_judge` from worker threads.
  A single connector is built lazily under `_judge_lock` so N workers do not each
  construct one.
- **The store.** Writes are serialised through the `ResultStore` connection.

Raising `concurrency` past a provider's rate limit makes a run *slower*, not
faster: every rejected call becomes a retry with backoff. See
[../operations/performance.md](../operations/performance.md).

## Retries

`_generate_with_retries` wraps every call, using `core/retry.py`:

1. **Classify.** `classify(exc)` decides retryable versus terminal without
   importing any provider SDK — it inspects `status_code`, `response.status_code`,
   `code`, and the exception's class name. A 401, 403, 400, 404 or 422 is
   terminal and fails immediately; 408, 409, 425, 429 and 5xx are retryable, as
   are connection and timeout errors.
2. **Unknown is retryable.** An unclassifiable error is far more often transient
   than terminal, and being wrong costs a couple of sleeps rather than a failed
   run.
3. **Full jitter.** `rng.uniform(0, min(cap, backoff * 2 ** attempt))`. Without
   it, `concurrency` workers that hit a rate limit together retry together and
   hit it again together.
4. **`Retry-After` wins.** When the provider says how long to wait, that value is
   used instead of the computed backoff.

The delay is capped at 60 seconds so a large `retries` value cannot hang a run.

Before this, a bad API key was retried `retries` times with sleeps, turning an
instant, clear failure into a slow, confusing one.

## Failure handling

| Failure | Effect |
|---|---|
| One call errors | Recorded as a `CallResult` with `status="error"`; the run continues |
| A scorer raises | That call is marked errored with the scorer name; the run continues |
| `run.fail_fast` is set and any call fails | `ArenaError` raised, run aborted |
| Anything escapes the loop | `_abort_run` closes the run out as `aborted` with partial results attached, then re-raises |

The abort path matters more than it looks. Without it, an interrupted run leaves
a row stuck at `status='running'` forever, and history becomes unreadable. The
`finally` block also closes every connector, so sockets are released whichever
way the run ended.

## Stopping early

`_should_stop` runs after each completion and returns a reason, or `None`.

| Reason | Trigger |
|---|---|
| `cancelled` | The caller set the runner's `cancel_event` |
| `budget` | Accumulated spend crossed `budgets.max_run_usd` or `max_model_usd`, with `on_exceed: stop` |

The check sits **between** calls, not inside one. A request already sent has
already been paid for, so abandoning its answer would waste the money without
saving any.

When it fires, pending futures are cancelled, the pool drains what is in flight,
and the collected results are kept — with a note on the leaderboard saying how
many of the planned calls they cover. A truncated sweep presented as a complete
one is exactly the quiet lie this project exists to avoid.

## What is not built yet

- **Resume.** An interrupted run cannot be continued; it starts over.
- **`confirm_above_usd`.** Parsed, but nothing prompts on it yet.

See [../roadmap/status.md](../roadmap/status.md).
