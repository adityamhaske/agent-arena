# Metrics and the leaderboard

`agent_arena/core/metrics.py` — how a pile of `CallResult` rows becomes a ranked,
gated answer. This module is the product; everything else feeds it.

## Four stages

```text
  results ──▶ aggregate ──▶ normalize ──▶ weight ──▶ constrain ──▶ leaderboard
             raw metrics    0–1 scale    composite   DISQUALIFIED
```

### 1. Aggregate

Per model, across every completed call:

| Metric | Computed as |
|---|---|
| `accuracy` | Weighted mean of case scores, using each case's `weight` |
| `cost` | Mean cost per call × 1,000 → USD per 1,000 calls |
| `latency` | Mean, plus p50/p95 percentiles |
| `error_rate` | Errored calls ÷ total |
| *(custom)* | Any number a scorer or connector emitted in `metrics` |

**Cost is all-or-nothing.** If any completed call lacks a price, `raw["cost"]`
is `None` rather than a partial mean:

```python
costs = [r.cost_usd for r in completed if r.cost_usd is not None]
if costs and len(costs) == len(completed):
    raw["cost"] = mean(costs) * 1000.0
else:
    raw["cost"] = None
```

A mean over the priced subset would be a fabricated number — it would read as
"this model costs X" when it means "the part of this model we could price costs
X". When cost is nulled and `metrics.weights` includes cost, the leaderboard
carries a warning naming the unpriced models and how to fix it.

### 2. Normalize

Raw metrics are in incomparable units — a percentage, dollars, milliseconds. Four
modes bring them to 0–1, selected per metric in `metrics.normalize`:

| Mode | Behaviour | Use for |
|---|---|---|
| `minmax` | Scale between the best and worst in this run | Metrics with no absolute meaning |
| `target` | Score against a ceiling from `metrics.targets` | Latency with an SLA |
| `budget` | Score against `cost.budget_usd_per_1k_calls` | Cost with a real budget |
| `raw` | Already 0–1 | Accuracy |

`direction` decides whether higher or lower is better; cost and latency are
lower-is-better, so their normalization inverts.

`target` and `budget` differ from `minmax` in an important way: they are absolute.
Under `minmax`, the cheapest model in a run always scores 1.0 for cost even if it
is over your budget. Under `budget`, being over budget is visible.

### 3. Weight

```yaml
metrics:
  weights: {accuracy: 0.55, cost: 0.25, latency: 0.20}
```

Weights are normalized to sum to 1, then the composite is their weighted sum.
A metric you do not weight does not affect the ranking, though it is still
reported.

Custom metrics work identically: a scorer that emits `{"citation_rate": 0.8}` can
be weighted as `citation_rate: 0.15` with no code change.

`tie_breaker` (default `accuracy`) orders models whose composites are equal.

### 4. Constrain

```yaml
constraints:
  min_accuracy: 0.70
  max_latency_p95_ms: 4000
  max_cost_per_1k_calls_usd: 2.0
  max_error_rate: 0.05
  min_context_tokens: 100000
  required_features: [tool_use, json_mode]
  privacy_required: [zero_retention]
  allow_unknown_card: true
```

A model violating any of these is **`DISQUALIFIED`**, not ranked low. It gets no
rank, and the reason is printed:

```text
  -  sim_tiny      mock:tiny  —  50.0%  $0.02  90ms  DISQUALIFIED
  ✗ sim_tiny: accuracy 50.0% below the required 70.0%
```

This is the module's central opinion. Ranking an unusable model fourth implies
the ordering is meaningful all the way down; disqualification changes the shape
of the answer, which is what an accuracy floor actually means.

`allow_unknown_card` decides whether a model with no capability card passes
feature and privacy constraints. Default `true` — absence of evidence is not
evidence of absence, and a local model has no card by definition.

## Honesty about resolution

When the top two composites are within a small margin, the leaderboard says the
sweep cannot separate them and suggests more trials, rather than crowning a
winner. A 12-case sweep does not have the resolution to distinguish models two
points apart, and presenting it with the same confidence as a runaway result is
the exact failure this project criticises in public benchmarks.

`core/statistics.py` now puts a number on that.

| What | How |
|---|---|
| **Confidence interval** per model | Percentile bootstrap over **test cases**, not trials |
| **Paired comparison** of the top two | Every model provably sees identical cases, so pairing cancels per-case difficulty — the largest source of variance in a small eval |
| **Power calculation** | "about 40 cases in total would separate them" |
| **Discriminating cases** | Where the leaders disagree; the rest is ballast |

Resampling over cases rather than trials is the load-bearing choice. A case is
the unit of generalisation: you want to know whether the ranking holds on *other
tasks like these*, not whether it holds if you asked the same twelve questions
again. Resampling trials would answer the second question and report it as the
first, shrinking every interval by a factor the data does not support.

The sentence it emits always names **accuracy**, because the leaderboard ranks
on the composite:

> `sim_small` and `sim_frontier` are too close to call on accuracy — about 14
> cases in total would separate them. Any gap between them here is coming from
> cost and speed.

Without that word, "indistinguishable" reads as "the ranking is meaningless",
when the real meaning is usually the opposite: the models answer about equally
well, so price and speed are deciding — and those are measured far more
precisely than accuracy is.

Configure with a `statistics:` block (`enabled`, `resamples`, `confidence`,
`seed`). On by default: leaving it off would make the less honest presentation
the easy one.

## Re-scoring without re-running

`build_leaderboard` takes results as an argument rather than fetching them, so
the same function ranks a live run and a stored one. The UI's what-if sliders
call it with stored results and different weights — no new API calls, no new
spend. Because it is the same function, a what-if and a fresh run can never
disagree. That is invariant 3: the UI never re-implements the engine.
