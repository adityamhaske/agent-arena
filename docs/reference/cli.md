# CLI reference

```bash
arena <command> [options]
arena --version
```

Every command that reads a project takes `--project PATH` (default `.`).

## `arena evaluate` (alias `run`)

Run the sweep.

| Flag | Type | Does |
|---|---|---|
| `--project` | path | Project folder or config file |
| `--models` | list | Only these models, by key or id |
| `--trials` | int | Override `run.trials` |
| `--concurrency` | int | Override `run.concurrency` |
| `--tags` | list | Only cases carrying any of these tags |
| `--exclude-tags` | list | Skip cases with these tags |
| `--ids` | list | Only these case ids |
| `--limit` | int | Cap the number of cases |
| `--output-dir` | path | Override `output.dir` |
| `--dry-run` | flag | Show the plan and cost estimate; call nothing |
| `--no-report` | flag | Skip writing report files |
| `--fail-under` | float | Exit non-zero if the winner's composite is below this |
| `--quiet` / `-q` | flag | Only print the summary |
| `--json` | flag | Print the run as JSON |

```bash
arena evaluate --project projects/support_triage
arena evaluate --project projects/support_triage --models claude-opus-5 --trials 3
arena evaluate --project projects/support_triage --tags billing --limit 20
arena evaluate --project projects/support_triage --dry-run
arena evaluate --project projects/support_triage --fail-under 0.75 --quiet   # CI gate
```

`--dry-run` is the one to reach for before any paid run: it prints the full
matrix and an estimated cost without making a call.

## `arena validate`

Check config, test files and credentials. Exits non-zero on a problem.

```bash
arena validate --project projects/my_project
```

Run this before `evaluate`. It catches a config typo in a second rather than
after a partial spend.

## `arena report`

Re-display a stored run.

| Flag | Does |
|---|---|
| `--run-id` | Which run (default: most recent) |

## `arena history`

Past runs and regressions between them.

| Flag | Does |
|---|---|
| `--model` | One model's trend across runs |
| `--limit` | How many runs (default 10) |
| `--flaky` | List cases with unstable outcomes |

`--flaky` is the useful one for improving a test set: a case that flips between
runs on the same model is either genuinely ambiguous or badly specified, and
either way it is weakening your ranking.

## `arena init`

Scaffold a project.

| Flag | Does |
|---|---|
| `path` | Where to create it (positional) |
| `--name` | Project name (defaults to the folder name) |
| `--force` | Write into a non-empty folder |

The scaffold runs immediately with no API key — CI asserts this.

## `arena models`

Model cards: price, context window, features.

## `arena scorers`

The available eval types.

## `arena tests`

The cases a project will run.

| Flag | Does |
|---|---|
| `--tags` | Filter by tag |
| `--limit` | Cap the count |

## `arena ui`

The browser interface.

| Flag | Default | Does |
|---|---|---|
| `--projects-dir` | `projects` | Where projects live |
| `--port` | `8420` | Port |
| `--host` | `127.0.0.1` | Bind address |
| `--no-browser` | | Do not open a browser window |
| `--verbose` | | Log every request |

```bash
arena ui
arena ui --projects-dir ~/work/evals --port 8421
```

Binding to a non-loopback host puts an unauthenticated API on your network. See
[../security/hardening.md](../security/hardening.md).

## Exit codes

| Code | Means |
|---|---|
| 0 | Success |
| 1 | An `ArenaError` — config problem, validation failure, or `--fail-under` not met |
| 130 | Interrupted |

## Lifecycle commands

### `arena projects`

List projects. `--projects-dir` (default `projects`), `--all` to include
archived ones.

### `arena runs`

List past runs for a project. `--limit`, and `--all` to include soft-deleted
runs.

### `arena label <run-id> --project <p>`

Give a run a human name, so it is not only `run_20260903_175823_38dd9f`.
`--label` and `--notes`.

### `arena archive project|run <name>`

Hide something from the default listings without destroying it. `--undo`
reverses it. Archiving a run needs `--project`.

### `arena duplicate <name> <new-name>`

Copy a project, **excluding** `results/` and any database. The copy's
`project:` field is rewritten so the two stay distinguishable.

### `arena rm project|run <name>`

Delete something.

| Flag | Does |
|---|---|
| `--dry-run` | Print the plan and exit; change nothing |
| `--yes` / `-y` | Skip the confirmation prompt |
| `--keep-results` | (projects) Remove config and scorers, keep `results/` |
| `--hard` | (runs) Remove outright instead of soft-deleting |
| `--project` | (runs) Which project the run belongs to |

```bash
arena rm run run_20260903_175823_38dd9f --project projects/my_project --dry-run
arena rm project old_experiment --keep-results --yes
```

The plan prints before the prompt, so you see exactly what will go. **A
non-interactive stdin without `--yes` refuses** rather than assuming yes — a
script that deletes a project because nobody was there to answer is the worst
available default.

A deleted run is soft-deleted: hidden from every listing and from history, and
recoverable until `arena vacuum`.

### `arena vacuum --project <p>`

Permanently remove soft-deleted runs and reclaim the file space. `--dry-run`,
`--yes`.

### `arena env --project <p>`

Show which `.env` files were found, nearest last. **Values are never printed.**

## Planned commands

`export`, `secrets`, `providers`, `config`, `watch`, and
`evaluate --resume` are designed but not built. See
[../roadmap/status.md](../roadmap/status.md).
