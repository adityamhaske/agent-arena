# Cost control

An evaluation is a spending event. Four mechanisms keep it deliberate.

## 1. Prove it offline first

`mock:` models have fixed accuracy, latency and price, and run with no network
and no credential.

```yaml
models:
  - key: sim_small
    model: mock:small
    card: {input_usd_per_mtok: 1, output_usd_per_mtok: 5}
```

```bash
arena evaluate --project projects/my_project --models sim_small
```

Prove your scorer grades correctly, your weights rank the way you intend, and
your constraints fire — all before spending anything. A scorer bug found on the
first real run has already cost you the whole sweep.

This is the single most effective cost control in the tool, and it is free.

## 2. Plan before you spend

```bash
arena evaluate --project projects/my_project --dry-run
```

Prints the matrix and an estimate; calls nothing. `models × cases × trials` grows
multiplicatively — four models, 50 cases and 3 trials is 600 calls, which is easy
to type and expensive to discover afterwards.

## 3. Know what a call costs

Cost comes from the price book (`model_cards.json`), a project pricing file, or a
per-model `card:` override.

```yaml
models:
  - key: my_model
    model: some-model
    card: {input_usd_per_mtok: 3.0, output_usd_per_mtok: 15.0}
```

### The all-or-nothing rule

**If any completed call lacks a price, the cost metric is `None` for the whole
run.** Not a partial mean — nothing.

That is deliberate. A mean over the priced subset would read as "this model costs
X" when it means "the part we could price costs X", and a purchasing decision
made on that number would be wrong in an invisible way.

The practical consequence: adding one unpriced model removes the cost axis for
every model in the run. The leaderboard warns when this happens and names the
unpriced models. Fix it with a `card:` override, a pricing file, or by having a
`run:` target report its own `cost_usd`.

Prices move. The catalog records `as_of`; verify against your provider before
making a decision on cost.

## 4. Limit the sweep

| Technique | Effect |
|---|---|
| `--limit 20` | Cap the cases |
| `--tags smoke` | A curated fast subset |
| `--trials 1` | Skip variance measurement |
| `--models <key>` | One model at a time |
| `enabled: false` | Park a model in config without deleting it |

```bash
arena evaluate --project p --tags smoke --trials 1 --limit 20
```

## Budgets

```yaml
budgets:
  max_run_usd: 5.00
  max_model_usd: 2.00
  confirm_above_usd: 1.00
  on_exceed: stop
```

This block **parses and validates today**. The runner does **not** enforce it
yet, so it is documentation of intent rather than a control. Until it lands, use
`--dry-run` and `--limit`. See [../roadmap/status.md](../roadmap/status.md).

## Constraints are not a cost control, but they help

```yaml
constraints:
  max_cost_per_1k_calls_usd: 2.0
```

This disqualifies a model that is too expensive *after* the run — it does not
prevent the spend. Its value is stopping an expensive model from winning, which
is a different and also useful thing.

## Watching a run

The progress line shows completed versus planned, and the summary prints total
spend:

```text
  4 models × 12 tests × 3 trial(s) = 144 calls in 0.0s
  Spend: $0.0199
```

A run in progress **cannot currently be cancelled** — the API has the plumbing
but the runner never checks the flag. Ctrl-C works from the terminal and closes
the run out as aborted with partial results kept. From the browser, there is no
stop. This is the most user-visible gap in the product; see
[../roadmap/status.md](../roadmap/status.md).

## Reviewing spend afterwards

```bash
sqlite3 projects/my_project/results/arena.sqlite \
  "SELECT run_id, started_at, total_cost_usd FROM runs ORDER BY started_at DESC LIMIT 10;"
```

```bash
sqlite3 projects/my_project/results/arena.sqlite \
  "SELECT model_key, COUNT(*), ROUND(SUM(cost_usd), 4)
   FROM results WHERE run_id = '<id>' GROUP BY model_key;"
```

There is no cross-project spend view yet.

## A safe first paid run

```bash
arena evaluate --project p --models sim_small          # 1. offline, free
arena validate --project p                             # 2. credentials present
arena evaluate --project p --dry-run                   # 3. see the plan
arena evaluate --project p --limit 5 --trials 1        # 4. tiny real run
arena evaluate --project p                             # 5. the real thing
```

Step 4 is the one people skip. Five real calls will surface a malformed request,
a wrong model id or a broken scorer for a few cents.
