# Your first project

## Scaffold

```bash
arena init projects/my_project --name my_project
```

That writes `config.yaml`, `tests.yaml` and `scorers/`. It runs immediately:

```bash
arena evaluate --project projects/my_project
```

CI asserts that, so a scaffold that does not run is a build failure.

## Describe the job

`config.yaml` is the whole contract. Work through it in this order — it is the
order the decisions actually depend on each other.

### 1. What competes

```yaml
models:
  - key: sim_small
    model: mock:small
    card: {input_usd_per_mtok: 1, output_usd_per_mtok: 5}
  - key: haiku
    model: claude-haiku-4-5
  - key: gpt5_mini
    model: gpt-5-mini
```

Keep at least one `mock:` model while you are building. It costs nothing and
gives you a fixed point to check your scorer and weights against.

A model whose API key is missing is **skipped, not failed** — the run continues
without it. So this config works before you have any keys.

### 2. What the model is told

```yaml
defaults:
  system: "Reply with exactly one label."
  max_tokens: 8
  temperature: 0
```

`temperature: 0` matters for evaluation: you are measuring the model, not its
sampling variance. Use `run.trials` to measure variance deliberately instead.

### 3. How answers are graded

```yaml
scorers:
  default: classification
  options:
    classification:
      labels: [billing, technical, account, other]
```

Ten builtins are available; `arena scorers` lists them. See
[../reference/scorers.md](../reference/scorers.md) to choose.

### 4. What "best" means

This is the part that is actually your job.

```yaml
metrics:
  weights: {accuracy: 0.55, cost: 0.25, latency: 0.20}
  cost:    {budget_usd_per_1k_calls: 2.0}
  latency: {target_ms: 800}
```

Ask concretely: at your volume, what does one percentage point of accuracy buy,
and what does it cost? A classifier handling 100,000 tickets a month has a very
different answer from one handling 200.

`budget_usd_per_1k_calls` and `target_ms` are absolute reference points. Without
them, `minmax` normalization scores the cheapest model in the run at 1.0 even if
it is over your budget.

### 5. What is non-negotiable

```yaml
constraints:
  min_accuracy: 0.70
  max_latency_p95_ms: 4000
```

A model violating one of these is `DISQUALIFIED`, not ranked low. This is the
most under-used part of the config and the most valuable: it converts "we should
probably not use that one" into a result the leaderboard enforces.

Set the floor at the level where you would genuinely refuse to ship, not at the
level you hope for.

## Write cases

`tests.yaml`:

```yaml
tests:
  - id: double_charge
    input: "I was charged twice for the same order this month."
    reference: billing
    tags: [billing, easy]

  - id: ambiguous_refund
    input: "The app crashed and now I want my money back."
    reference: billing
    tags: [billing, hard, ambiguous]
```

Advice that matters more than the config:

- **Write the ambiguous ones.** Easy cases every model gets right carry no
  information about which model to pick. The cases that discriminate are the ones
  you are unsure about.
- **`id` is a database key.** Renaming one detaches it from its own history.
- **Tag by difficulty and by topic.** Then `--tags hard` tells you where models
  actually differ.
- **Twelve cases is a demo, not an evaluation.** Enough cases to separate two
  models is usually dozens. The leaderboard will tell you when it cannot.

## Validate, plan, run

```bash
arena validate --project projects/my_project
```

Checks config, test files and credentials. Catches a typo in a second rather than
after a partial spend.

```bash
arena evaluate --project projects/my_project --dry-run
```

Prints the full matrix and a cost estimate without making a call. Always do this
before the first paid run — `trials × cases × models` grows faster than people
expect.

```bash
arena evaluate --project projects/my_project
```

## Iterate

```bash
arena history --project projects/my_project           # runs over time
arena history --project projects/my_project --flaky   # unstable cases
```

`--flaky` is the one that improves your test set. A case that flips between runs
on the same model is either genuinely ambiguous or badly specified, and either
way it is adding noise to your ranking.

If the leaderboard says your top two are too close to call, it means it — add
cases rather than reading the third decimal place.
