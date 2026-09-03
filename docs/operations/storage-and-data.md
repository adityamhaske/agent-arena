# Storage and data

## Layout

```text
projects/my_project/
├── config.yaml
├── tests.yaml
├── scorers/
├── hooks.py
└── results/                     # output.dir
    ├── arena.sqlite             # every call from every run
    └── run_20260903_175823_38dd9f/
        ├── report.md
        └── results.json
```

Override with:

```yaml
output:
  dir: results
  db: results/arena.sqlite
  formats: [markdown, json]
```

Point several projects at one database by giving them the same `db` path — rows
carry a `project` column, so they stay separable.

## The run id

`run_<UTC timestamp>_<random>` — for example `run_20260903_175823_38dd9f`. It is
the primary key in `runs`, the results subdirectory name, and the argument to
`arena report --run-id`.

## Querying directly

It is plain SQLite. Nothing stops you.

```bash
sqlite3 projects/my_project/results/arena.sqlite
```

**Recent runs:**

```sql
SELECT run_id, started_at, winner, n_results, total_cost_usd
FROM runs WHERE project = 'my_project'
ORDER BY started_at DESC LIMIT 10;
```

**Where a model failed:**

```sql
SELECT test_id, trial, score, reason, substr(output, 1, 80)
FROM results
WHERE run_id = '<id>' AND model_key = 'sim_small' AND passed = 0;
```

**Cases no model gets right** — usually the most valuable query in the database,
because it finds broken references and impossible cases rather than bad models:

```sql
SELECT test_id, COUNT(*) AS attempts, SUM(passed) AS passes
FROM results WHERE run_id = '<id>'
GROUP BY test_id HAVING passes = 0;
```

**Accuracy over time for one model:**

```sql
SELECT r.started_at, AVG(res.score) AS accuracy
FROM results res JOIN runs r ON r.run_id = res.run_id
WHERE res.project = 'my_project' AND res.model_key = 'sim_small'
GROUP BY r.run_id ORDER BY r.started_at;
```

**Spend by model:**

```sql
SELECT model_key, COUNT(*) AS calls, ROUND(SUM(cost_usd), 4) AS usd
FROM results WHERE run_id = '<id>' GROUP BY model_key;
```

Schema details: [../architecture/data-model.md](../architecture/data-model.md).

## Reproducibility

Every run stores `config_json` — the complete config as it was — plus
`arena_version` and `git_sha`. So a leaderboard from months ago can be
attributed: what ran, under which weights, from which commit.

```sql
SELECT config_json FROM runs WHERE run_id = '<id>';
```

That snapshot is also what makes re-scoring possible without re-running.

## Size

The `results` table is the bulk of it. `output` is truncated at 20,000
characters; a run that stored full long-context outputs would grow faster than
the value justifies.

```bash
ls -lh projects/my_project/results/arena.sqlite
sqlite3 ... "SELECT COUNT(*) FROM results;"
```

A few hundred runs of a few hundred calls is comfortably a few tens of megabytes.

## Cleaning up

```bash
arena rm run <run-id> --project projects/my_project --dry-run   # see the plan
arena rm run <run-id> --project projects/my_project             # soft delete
arena vacuum --project projects/my_project                      # reclaim space
```

A run is **soft-deleted** by default: hidden from every listing, from history
and from trends, but still on disk and recoverable until `vacuum`. Its report
files under `results/<run_id>/` are removed immediately.

| Command | Effect |
|---|---|
| `arena rm run <id>` | Soft delete — recoverable |
| `arena rm run <id> --hard` | Removes the rows outright, cascading to results and rankings |
| `arena vacuum` | Hard-removes every soft-deleted run, then reclaims file space |
| `arena rm project <name>` | Removes the whole folder |
| `arena rm project <name> --keep-results` | Removes config and scorers, keeps `results/` |

Every one of them prints the plan before asking, and `--dry-run` prints it
without doing anything. A non-interactive shell without `--yes` refuses rather
than assuming yes.

### The schema behind it

Soft delete is a `deleted_at` timestamp on `runs`, added by schema version 2.
A database created by an earlier version is migrated on first open, driven by
sqlite's `user_version` pragma — additive `ALTER TABLE` statements only, so no
row is rewritten or lost.

## Backing up

The database is a single file. Copy it:

```bash
cp projects/my_project/results/arena.sqlite backup-$(date +%F).sqlite
```

Use SQLite's own backup command if a run may be in progress:

```bash
sqlite3 projects/my_project/results/arena.sqlite ".backup 'backup.sqlite'"
```

## Committing results

Worth doing for a small project: it makes runs reviewable in a pull request and
gives CI history to compare against. `projects/local_demo/results/` is committed
for exactly that reason.

For a large or frequently-run project, keep it out of git — the database is
binary and will bloat history. Cache it in CI instead.

## Exporting

`ResultStore.export_csv(run_id, path)` exists at the Python level. There is no
`arena export` command yet; the reports in `results/<run_id>/` are markdown and
JSON, and the JSON is the machine-readable one. CSV, HTML and a CLI command are
planned.
