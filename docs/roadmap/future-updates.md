# Future updates

Grouped by the problem each solves. See [status.md](status.md) for what exists
today, and the
[v2 plan](../superpowers/plans/2026-09-02-agent-arena-v2-launch.md) for detail.

## 1. Connect what is already built

**Problem.** Credential references, user settings, provider profiles and `.env`
parsing are complete and tested, and none of them affect a real run because
nothing calls them. That is the single largest gap between what the code contains
and what the product does.

**Work.** Wire `core/env.py` into `cli.main()`; route the runner through
`ProjectConfig.provider_for()` so headers, custom CAs, proxies and model-prefix
rewriting apply; resolve credentials through `service/secrets.py` instead of
reading `os.environ` directly; read defaults from `service/settings.py`.

**Size.** Small — this is wiring, not new design. Highest value per hour of
anything on this page.

## 2. The rest of the service layer, and delete

**Problem.** There is no way to delete a project or a run. A project created by a
typo is permanent, and the database grows forever. `web/api.py` still holds
project CRUD the CLI cannot reach, which is the reason the gap exists.

**Work.** `service/projects.py`, `service/runs.py`, `service/providers.py`,
`service/export.py`; store schema v2 with soft delete and a migration runner;
`arena rm`, `export`, `duplicate`, `archive`, `vacuum`, `label`; a `do_DELETE`
handler and the routes for it. Every destructive operation returns the same plan
whether or not `dry_run` is set, so a confirmation dialog cannot lie.

**Size.** Medium. The contract is already specified.

## 3. Cancellation and budgets

**Problem.** A misconfigured sweep against a paid API cannot be stopped. This is
the one bug in the product that costs real money while you watch.

**Work.** A cooperative cancel check in the runner's completion loop; live cost
accumulation compared against `budgets.max_run_usd` and `max_model_usd`; stopping
with partial results preserved and clearly labelled partial; a confirmation
prompt above `confirm_above_usd`.

**Size.** Small–medium. Both config blocks already parse.

## 4. The multi-page interface

**Problem.** Eight hash routes behind a two-link topbar. No settings, no
cross-project view, no way to manage a credential, no delete. The interface is
the part of the product a new user judges first.

**Work.** A sidenav shell with sixteen routes and nine settings sub-pages; a
run detail view with a per-case × per-model grid; Compare; a Providers page with
a live connection test; a Cases library with CSV/JSONL import. Server-sent events
replacing polling. A token-authenticated mode for non-loopback binds.

The approved approach keeps the engine stdlib-only and puts FastAPI plus a
**pre-built** front-end bundle behind an optional `agent-arena[ui]` extra, so the
default install stays dependency-free and no user ever runs npm.

**Size.** Large — the biggest item here, and the most visible.

## 5. Resumable runs

**Problem.** A 45-minute sweep that dies at 90% starts over and re-spends.

**Work.** An idempotency key per `(run_id, model_key, test_id, trial)`;
`arena evaluate --resume <run_id>` skipping completed cells.

**Size.** Small, once the store has a schema version.

## 6. Defensible statistics

**Problem.** The leaderboard refuses to crown a winner inside the noise floor,
but it cannot say *how much* more evidence would settle it, and it reports no
interval. Three models within two points look as confident as a runaway result.

**Work.** Bootstrap confidence intervals resampled over **test cases** — cases
are the unit of generalisation, not trials. Paired comparison, which is far more
sensitive here because every model provably sees identical cases. A power
calculation: *"separating your top two at 95% confidence needs about forty more
cases."* Per-case discriminative value, so you know which cases are worth
curating and which are ballast. Error bars in the UI, and one plain sentence when
two models are indistinguishable.

Every input is already in SQLite. Stdlib `statistics` and `random` only.

**Size.** Medium, and fully testable offline against mock models.

## 7. Continuous evaluation — shipped

`arena watch` compares a fresh run against the mean of its own recent history
and flags a real move — a composite drop or a status change — with a webhook
for alerting and `--fail-on-drift` for a CI gate. See
[../guides/continuous-evaluation.md](../guides/continuous-evaluation.md).

`.github/actions/agent-arena-eval` runs on PRs and comments the leaderboard,
with an optional baseline diff; `--fail-under` gates it when you are ready.
Dogfooded in this repo by `.github/workflows/pr-eval-demo.yml`. See
[../guides/ci-integration.md](../guides/ci-integration.md).

`arena models` and `arena validate` warn when the price catalog's `as_of` is
past 90 days — a different kind of drift, the catalog going stale rather than
a model's accuracy, but the same underlying concern.

Remaining: `arena watch --loop` reinvents a scheduler rather than integrating
with one properly (cron, systemd timers), which is fine for now and could grow
a native "run under launchd/systemd" mode later if anyone asks for it.

## 8. Test cases from reality

**Problem.** Every evaluation is only as good as its cases, and hand-written
cases are the weakest part of any eval. People write the easy ones, miss the
ambiguous ones, and get a confident recommendation from a set that does not
resemble production.

**Work.** Import from CSV, JSONL, or a query against your own logs. Coverage
analysis by tag. **Disagreement mining** — the highest-information case is one
where the leading models split, and the store already holds every model's answer
to every case, so it can point at exactly those. A one-line hook so production
failures land in the test file.

**Size.** Small for import and disagreement mining. Larger for clustering, which
would want an optional embedding dependency — kept optional, per the dependency
policy.

## Smaller items

| Item | Why |
|---|---|
| CSRF/`Origin` check on the local API | A known gap in [../security/threat-model.md](../security/threat-model.md) |
| Reject a request with no `Host` header | Same |
| Automated accessibility checks in CI | axe-core in a Playwright run, dev-only |
| First PyPI release | The workflow is ready; no tag has been pushed |
| Context windows in the price catalog | Cards carry the field; most entries leave it null |

## Sequencing

```text
  1. Connect what exists      ──▶ makes the built foundation real
  2. Service layer + delete   ──▶ closes the most visible product gap
  3. Cancellation + budgets   ──▶ stops the tool costing money uncontrollably
  4. Multi-page UI            ──▶ the large one, needs 1-3 underneath it
  5. Resume                   ──▶ independent, cheap
  6. Statistics               ──▶ independent; makes the answer defensible
  7. Continuous               ──▶ makes the answer stay true
  8. Cases from production    ──▶ makes the question worth asking
```

Items 6, 7 and 8 are independent of the rest and of each other.
