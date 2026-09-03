# Performance

## What governs wall-clock

```text
duration  ≈  (models × cases × trials / concurrency) × per-call latency
             + retry overhead
```

Four terms, and only two are usefully under your control.

| Term | Control |
|---|---|
| Matrix size | `--limit`, `--tags`, `--trials`, `--models` |
| Concurrency | `run.concurrency` |
| Per-call latency | The provider's, and your `max_tokens` |
| Retry overhead | Indirect — caused by exceeding rate limits |

## Concurrency has an optimum, not a maximum

Default is 4. Raising it helps **until you hit the provider's rate limit**, after
which it actively hurts: every rejected call becomes a retry with exponential
backoff, so more workers produce more rejections and more sleeping.

```yaml
run:
  concurrency: 8
```

Find the ceiling empirically. Run a small sweep at 4, 8, 16 and compare wall
clock:

```bash
time arena evaluate --project p --limit 20 --concurrency 4  --quiet --no-report
time arena evaluate --project p --limit 20 --concurrency 16 --quiet --no-report
```

If 16 is not meaningfully faster than 8, you are at the limit. If it is *slower*,
you are past it.

**Local models are different.** A single GPU serves requests roughly serially;
high concurrency queues rather than parallelises, and can cause timeouts. Start
at 1–2 and measure.

Jitter in the retry path means concurrent workers no longer retry in lockstep —
before that fix, hitting a rate limit with 8 workers produced a synchronised
thundering herd that hit it again immediately.

## The matrix dominates everything else

```text
 4 models × 12 cases × 3 trials =  144 calls
 4 models × 50 cases × 3 trials =  600 calls
 6 models × 100 cases × 5 trials = 3,000 calls
```

At one second per call and concurrency 8, the last is over six minutes — and it
costs six minutes' worth of tokens too.

While iterating, cut the matrix rather than tuning concurrency:

```bash
arena evaluate --project p --models sim_small --limit 5    # instant, free
arena evaluate --project p --tags smoke --trials 1
```

## Per-call latency

`max_tokens` is the lever people forget. A classification task that needs one
word does not need 1,024 tokens of headroom:

```yaml
defaults:
  max_tokens: 8
```

Generation time is roughly linear in tokens produced, so this is often the
largest single win on a classification sweep — and it reduces cost at the same
time.

## Timeouts

```yaml
run:
  timeout_s: 120.0
```

Too low and slow-but-valid calls fail and retry, which is strictly worse than
waiting. Too high and one hung call holds a worker for the full duration. Set it
to comfortably above your slowest legitimate call, not to your average.

## Retry overhead

Retries are already classified, so terminal failures do not sleep. What remains
is genuine rate limiting, and the fix is concurrency, not `retries`.

Lowering `retries` to hide rate limiting converts slow runs into failed calls.
Lower the concurrency instead.

## Scorer cost

Most scorers are microseconds. Two are not:

- **`llm_judge`** makes a second model call per case. It can double or triple
  wall-clock and cost. Consider judging a sample rather than every case.
- **`code_exec`** spawns a subprocess per case, so it is bounded by process
  startup and by the code's own runtime.

## The database

SQLite writes are serialised, but each write is small and vastly faster than a
model call, so it is not the bottleneck. The database only becomes noticeable in
the offline mock case, where calls are free and instant — which is exactly the
case where nobody is waiting.

## Measuring

The summary prints the wall clock:

```text
  4 models × 12 tests × 3 trial(s) = 144 calls in 0.0s
  Spend: $0.0199
```

Per-model latency is in the leaderboard, and per-call in the database:

```sql
SELECT model_key, COUNT(*) AS calls,
       ROUND(AVG(latency_ms)) AS mean_ms,
       ROUND(MAX(latency_ms)) AS max_ms,
       SUM(attempts) - COUNT(*) AS retries
FROM results WHERE run_id = '<id>' GROUP BY model_key;
```

That `retries` column is the diagnostic: a number well above zero means you are
being rate limited, and concurrency is too high.

## A tuning order

1. Cut the matrix while iterating. Nothing else comes close.
2. Lower `max_tokens` to what the task needs.
3. Raise concurrency until the retry count climbs, then back off one step.
4. Set `timeout_s` above your slowest legitimate call.
5. Only then worry about anything else.
