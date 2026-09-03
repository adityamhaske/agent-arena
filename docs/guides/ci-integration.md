# CI integration

Gate a merge on evaluation results.

> A dedicated GitHub Action is planned, not shipped. What follows works today
> with a plain workflow step.

## The gate

`--fail-under` exits non-zero when the winner's composite is below a threshold:

```bash
arena evaluate --project projects/my_project --fail-under 0.75 --quiet
```

That is the whole mechanism. Everything else is plumbing.

## A workflow

```yaml
name: Evaluate

on:
  pull_request:
    paths:
      - 'prompts/**'
      - 'pipelines/**'
      - 'projects/my_project/**'

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: pip

      - run: pip install 'agent-arena[anthropic]'

      - name: Validate first
        run: arena validate --project projects/my_project

      - name: Evaluate
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          arena evaluate --project projects/my_project \
            --fail-under 0.75 --quiet

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: evaluation
          path: projects/my_project/results/
```

`paths:` matters. Evaluations cost money; running one on a README change is
waste.

## Keep the offline check separate

Split the free check from the paid one, and put the free one first:

```yaml
      - name: Offline sanity — scorers and weights behave
        run: arena evaluate --project projects/my_project --models sim_small --quiet

      - name: Real models
        if: github.event_name == 'pull_request'
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: arena evaluate --project projects/my_project --fail-under 0.75 --quiet
```

A broken scorer should fail in seconds against a mock model, not after spending
on a real one.

## Cost control in CI

| Technique | Effect |
|---|---|
| `--limit 20` | Cap the cases on a PR; run the full set nightly |
| `--tags smoke` | A curated fast subset |
| `--trials 1` | Skip variance measurement on a PR |
| `--dry-run` on draft PRs | Show the plan, spend nothing |
| `paths:` filters | Do not run at all when nothing relevant changed |

```bash
arena evaluate --project projects/my_project --tags smoke --trials 1 --limit 20 \
  --fail-under 0.75 --quiet
```

## Machine-readable output

```bash
arena evaluate --project projects/my_project --json > result.json
```

Then post a comment, feed a dashboard, or assert on specific values:

```bash
python -c "
import json, sys
r = json.load(open('result.json'))
w = r['leaderboard']['entries'][0]
print(f\"::notice::Winner {w['key']} at {w['composite']:.3f}\")
sys.exit(0 if w['composite'] >= 0.75 else 1)
"
```

## Tracking regressions over time

Commit the SQLite database, or restore it from a cache, and the history commands
work in CI:

```yaml
      - uses: actions/cache@v4
        with:
          path: projects/my_project/results/arena.sqlite
          key: arena-db-${{ github.ref }}
```

```bash
arena history --project projects/my_project --limit 5
```

That turns a single-point check into a trend, which is what catches a provider
silently changing a model underneath you.

## Secrets

- Use your CI provider's secret store; never a literal key in a workflow file.
- Scope the key to the minimum the evaluation needs.
- A missing key means models are **skipped**, not failed — so a misconfigured
  secret can produce a green build that evaluated only your mock models. Assert
  on the model list, or use `arena validate`, which fails on missing credentials.

That last point is the one that bites. `arena validate` before `arena evaluate`
is what turns it from a silent no-op into a failure.

## Planned

A published action that runs on PRs touching prompts or pipeline code and
comments the leaderboard delta. See
[../roadmap/future-updates.md](../roadmap/future-updates.md).
