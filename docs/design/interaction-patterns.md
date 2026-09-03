# Interaction patterns

Patterns for the three interactions this tool gets wrong most easily: destroying
something, spending money, and having nothing to show.

## Destructive actions

These rules are recorded in [../../AGENTS.md](../../AGENTS.md) because they bind
the service layer, not just the UI.

### The plan is the confirmation

Every destructive service function takes `dry_run: bool = False` and returns
**the same plan dict either way** — one code path, one branch at the end.

```python
plan = delete_project(projects_dir, "old-triage", dry_run=True)
# {"deleted": False, "name": "old-triage",
#  "paths": [...], "runs_removed": 14, "bytes": 2_400_112}
```

The confirmation dialog renders that dict. If the plan and the execution could
diverge, the dialog would be lying about what is going to happen — and a user who
learns that once will never trust a confirmation again.

### Reversible gets undo; irreversible gets typed confirmation

| Action | Pattern |
|---|---|
| Delete a test case | Immediate, with a 10-second undo toast |
| Archive a project or run | Immediate, reversible, no confirmation |
| Delete a run | Soft delete; recoverable until `vacuum` |
| Delete a project | Typed name confirmation, plus a *keep results* option |
| Delete all data | Typed confirmation, after listing exactly what will be destroyed |

A confirmation dialog that only says "Are you sure?" trains people to click
through. One that says *"This removes 14 runs and 2.4 MB"* is information.

### Archive is not delete

Archived objects leave the default listings and stay fully queryable. Most of the
time "I don't want to see this any more" is what someone means, and offering only
deletion pushes them into an irreversible action to get a reversible outcome.

### Non-interactive means refuse

On the CLI, a destructive command with no tty and no `--yes` must **refuse**, not
assume yes. A script that deletes a project because nobody was there to answer is
the worst possible default.

## Long-running, money-spending actions

A run is a spending event, and the interaction has to reflect that.

| Stage | What the user gets |
|---|---|
| Before | `--dry-run`: the plan and a cost estimate, with nothing spent |
| Above a threshold | Explicit confirmation before starting (`budgets.confirm_above_usd`) |
| During | Completed/planned, elapsed, ETA, accumulated cost, and a live feed of actual outputs |
| During | A cancel control reachable from anywhere |
| On breach | Stop, with partial results preserved **and labelled partial** |
| After | The leaderboard, with any resolution warnings |

The live output feed matters more than the progress bar: a bar says something is
happening, real outputs say whether it is happening *correctly* — early enough to
stop.

**Not built yet:** the runner has no cooperative cancellation check and does not
enforce budgets, so the cancel control cannot currently stop a sweep and the caps
do not fire. This is the largest gap between the designed and shipped
interaction. See [../roadmap/status.md](../roadmap/status.md).

## Empty states

Every list has a first-run state, and it should teach rather than apologise.

| Screen | Empty state should |
|---|---|
| No projects | Offer the wizard *and* point at an example that runs with no API key |
| No runs | Explain what a run produces, with the button to start one |
| No test cases | Show the two-field shape of a case with one filled-in example |
| No providers | Explain that mock and local models need no credential |

The first one is the most valuable in the product: someone can reach a real
leaderboard with no key and no config, which is the fastest way to understand
what the tool does.

## Errors

- Say what went wrong and what to do next.
- Never show a traceback; `plain_error` maps exceptions to sentences.
- Distinguish *skipped* from *failed*. A model without a key is skipped and the
  run continues — presenting that as a failure would send people hunting for a
  bug that is not there.

## Latency

| Duration | Treatment |
|---|---|
| Under ~100 ms | Nothing |
| Up to a second | Inline spinner on the control |
| Longer, known length | Progress with counts |
| Longer, unknown | Progress with elapsed time and a cancel control |

A run is always the last case. It has no reliable length, because provider
latency is not knowable in advance.
