# Continuous evaluation

A model choice decays. Providers update models silently, prompts drift,
traffic shifts, prices change. `arena watch` re-evaluates a project and
compares the fresh result against its own recent runs, so a decision made
three weeks ago stays an answer rather than a snapshot.

## The basic loop

```bash
arena watch --project projects/my_project
```

```text
my_project — run_20260904_074818_782937:
    sim_small: first watch run — no history to compare against yet.
```

Run it again after another evaluation has happened, and it compares:

```text
my_project — run_20260904_090201_9e3b1c:
  ! sim_small dropped 50 points versus its last 1 run(s) (85% -> 35%).
```

The `!` marks a **flagged** model — one that moved by more than the drift
threshold (5 percentage points by default), or whose status changed (a model
that started clearing its constraints and stopped, or the reverse).

## What counts as drift

The baseline is the **mean composite over recent prior runs**, not just the
run immediately before. Averaging absorbs one noisy prior run instead of
chasing it — a single unlucky sweep should not itself look like drift.

A model that has been steadily `DISQUALIFIED` across every run is **not**
flagged again each time; only a *change* in status is drift. Read the sentence
carefully:

- `"dropped 12 points"` / `"improved by 12 points"` — a real accuracy move
- `"changed status: ranked -> failed"` — it started failing a constraint
- `"disqualified this run"` — steady-state, not new information
- `"skipped this run"` — a credential problem, not a model problem
- `"first watch run"` — nothing to compare against yet

## Configuring it

```yaml
watch:
  drift_threshold: 0.05    # composite points that count as drift
  webhook: https://hooks.example.com/agent-arena
```

Both are optional, and a CLI flag always overrides the config value for one
run:

```bash
arena watch --project p --threshold 0.1 --webhook https://...
```

## Options

| Flag | Does |
|---|---|
| `--threshold` | Composite delta that counts as drift (default 0.05, or `watch.drift_threshold`) |
| `--history N` | How many prior runs form the baseline (default 5) |
| `--webhook URL` | POST a JSON report here when anything is flagged |
| `--fail-on-drift` | Exit 1 if anything is flagged — for a CI gate |
| `--loop --interval S` | Keep re-running every `S` seconds instead of once |
| `--json` | One JSON line per tick, for piping elsewhere |
| `--quiet` | Only print flagged models |

## Running it on a schedule

`arena watch` does one evaluation per tick — the same cost as `arena evaluate`
against that project. Two ways to schedule it:

**A cron entry, or a scheduled GitHub Actions workflow** (the more common
choice — someone else's scheduler, rather than a process you keep alive):

```yaml
on:
  schedule:
    - cron: "0 9 * * *"   # daily at 09:00 UTC

jobs:
  watch:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install agent-arena
      - run: arena watch --project projects/my_project --fail-on-drift
```

**`--loop`**, for a long-running process (a container, a small VM):

```bash
arena watch --project p --loop --interval 86400   # once a day
```

Prefer the scheduler when you have one. `--loop` reinvents what cron already
does, and exists for environments where a scheduler is the harder thing to set
up.

## The webhook payload

```json
{
  "project": "my_project",
  "run_id": "run_20260904_090201_9e3b1c",
  "flagged": [
    {
      "model_key": "sim_small",
      "current_composite": 0.35,
      "baseline_composite": 0.85,
      "delta": -0.50,
      "current_status": "ranked",
      "status_changed": false,
      "flagged": true,
      "sentence": "sim_small dropped 50 points versus its last 1 run(s) (85% -> 35%)."
    }
  ]
}
```

Fires only when something is flagged, and never raises on delivery failure —
a broken webhook is reported on stderr but does not make the evaluation itself
look like it failed.

## Watching for pricing drift

`arena models` and `arena validate` also warn when the shipped price catalog
itself is stale (past 90 days since `as_of`):

```text
! pricing     catalog is 94 days old (as of 2026-06-01) — verify against your
              provider before deciding on cost
```

This is a different kind of drift — the catalog going stale, not a model's
accuracy — but it is the same underlying concern: a number you are relying on
may no longer be true.
