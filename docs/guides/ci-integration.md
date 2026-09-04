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

## The published action

`.github/actions/agent-arena-eval` wraps the steps above into one action:
install, evaluate, and comment the leaderboard on the pull request.

```yaml
- uses: adityamhaske/agent-arena/.github/actions/agent-arena-eval@main
  with:
    project: projects/support_triage
    fail-under: "0.75"        # optional; omit to comment without gating
```

| Input | Default | Does |
|---|---|---|
| `project` | *(required)* | Path to the project folder |
| `fail-under` | *(none)* | Fails the step if the winner's composite is below this |
| `baseline` | *(none)* | Path to an `arena export --format json` file — usually the base branch's result — to show a delta column instead of just the new numbers |
| `install-extra` | *(none)* | e.g. `anthropic`, for a project using a real provider |
| `github-token` | `${{ github.token }}` | Needs `pull-requests: write` to post the comment |
| `python-version` | `3.12` | |

| Output | Is |
|---|---|
| `composite` | The winner's composite, or empty if everything was disqualified |
| `winner` | The winner's model key |
| `result-path` | Path to the full JSON result, for a later step to inspect |

The comment is **updated in place** on every push to the PR rather than
growing a new one each time — it is identified by an HTML comment marker, the
usual convention for a bot comment that repeats.

### Comparing against the base branch

```yaml
jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Get the base branch's result
        run: |
          git fetch origin ${{ github.base_ref }} --depth=1
          git show origin/${{ github.base_ref }}:projects/my_project/results/baseline.json             > baseline.json || echo '{"rankings":[]}' > baseline.json

      - uses: adityamhaske/agent-arena/.github/actions/agent-arena-eval@main
        with:
          project: projects/my_project
          baseline: baseline.json
```

That assumes a `baseline.json` is committed and refreshed on `main` — for
example via `arena export --format json --out projects/my_project/results/baseline.json`
in a workflow that runs on push to `main`. Without one, the action still posts
the leaderboard; it just has no delta column.

### The demo in this repo

`.github/workflows/pr-eval-demo.yml` dogfoods the action against
`projects/support_triage` on every PR that touches it — offline, with `mock:`
models, so it costs nothing and needs no secret. It is the action's own proof
that it actually works in real GitHub Actions, on top of the unit tests in
`tests/test_pr_comment_action.py`.

### Never a hard gate the first time

Land the action **without** `fail-under` first, so it comments for a few PRs
before anything can block a merge. A ranking is only worth gating on once
someone has actually looked at what it says.
