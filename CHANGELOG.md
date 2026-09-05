# Releases

All notable changes to Agent Arena. This file is the source for the
[Releases page](https://adityamhaske.github.io/agent-arena/releases/) on the
documentation site — the page is rendered from this file, so publishing a
release means editing here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.0.0] - 2026-09-05

The 2.0 line, promoted from `2.0.0rc3` and the first release published to the
real index. Three release candidates went to TestPyPI; what changed since rc3 is
one fix, below.

The headline of 2.0 is that the arena stopped being only about models. A
**target** — any Python callable, now including an `async def` one — is graded,
ranked and disqualified by exactly the machinery a model is, so the thing on the
leaderboard can be a whole pipeline, an agent architecture, or an application
from another repository entirely. The rest is the browser UI, resumable sweeps,
rate limiting, bootstrap confidence intervals, and `arena watch` for continuous
evaluation. See the three release-candidate sections below for the detail.

### Fixed

- **`preflight` healthchecks pipeline targets.** `CallableConnector.healthcheck`
  has always imported the target before a run — "so a typo costs nothing" — but
  `preflight` only called it for local endpoints, so nothing ever ran it. A
  target with a wrong path passed `arena validate` as "valid and ready" and then
  failed identically on every call, which reads as a model that answers nothing
  rather than as a path that is wrong.

  Targets are now healthchecked alongside local servers and skipped with their
  import error as the reason, and `arena validate`'s summary line names that
  third cause.

### Changed

- `projects/mara` checks for the assistant it evaluates at import rather than on
  first call, so a missing checkout surfaces at `arena validate` with the
  environment variable to set. It is the one example here that needs a
  repository other than this one, and CI cannot exercise it for that reason.

### Tests

- 721, up from 719: two cover a target that cannot be imported being caught by
  preflight rather than by the sweep.

---

## [2.0.0rc3] - 2026-09-04

### Added

- **Async targets.** A target declared `async def` is now awaited by the
  connector instead of returning a coroutine the scorer cannot read. Agent
  frameworks are async-first — LangGraph, LlamaIndex and most tool loops hand
  you a coroutine — so the previous behaviour taxed the common case: every
  adapter had to open with the same `asyncio.run` wrapper, and the one that
  forgot got a confusing error about the return type rather than an honest one
  about the shape of its function.

  The runner calls connectors on worker threads, so this is `asyncio.run` in
  every real sweep. Embedding the runner inside your own async program is the
  other branch: a loop is already running on that thread, so the coroutine gets
  its own loop on a thread of its own rather than deadlocking.

- **`projects/mara/` — example 6: an external multi-agent application.** Every
  other example evaluates something written for the arena. This one points at a
  separate codebase — a four-agent LangGraph research assistant (planner →
  executor → critic → synthesizer) in its own repository — and compares three of
  its depth settings, which is the configuration question you actually have to
  answer before shipping such a thing.

  It runs offline out of the box on the assistant's own scripted provider, and
  is deliberately honest about what that proves: the wiring and the report's
  structure, not which depth is better, because a fixture answer is the same
  answer at every depth. The leaderboard says so — `within noise for a small
  sweep` — instead of ranking three identical rows and calling it a result.

  Two details in the adapter are the reusable part: it drives the app through
  its **local host** (SQLite checkpointer, in-process event sink) rather than
  its HTTP API, and it gives every call a **fresh temporary data directory**, so
  no test case can warm a search cache that a later one then benefits from.

### Documentation

- `docs/guides/comparing-pipelines.md` gains an async example and a section on
  connecting a separate codebase, including why the two adapter decisions above
  matter for a fair comparison.
- The README's layout table lists example 6, and a new section covers pointing
  the arena at your own application.

### Tests

- 719, up from 715: four cover async targets — awaited, self-reporting, raising
  through, and driven from inside a running event loop.

---

## [2.0.0rc2] - 2026-09-04

### Added

- **`arena evaluate --resume <run-id>`.** A sweep that died at 90% has already
  paid for those calls; starting over spends the money twice. Only successful
  calls are skipped — an errored one is exactly what a resume is meant to retry.
- **Per-provider rate limiting.** `providers[].rate_limit` now applies: token
  buckets for `rpm` and `tpm`, a semaphore for `concurrency`, and an optional
  `burst` for smoothing. A run that waited says so on the leaderboard, because
  otherwise it is just mysteriously slow.
- **Statistics** (`core/statistics.py`): bootstrap confidence intervals, a
  paired comparison of the top two, a power calculation, and the cases where
  the leaders most disagree. Resampled over **test cases**, not trials — a case
  is the unit of generalisation, and resampling trials would shrink every
  interval by a factor the data does not support. Configurable via a
  `statistics:` block; on by default.

  The sentence it emits names accuracy explicitly, because the leaderboard
  ranks on the composite. "Indistinguishable" without that word reads as "the
  ranking is meaningless", when it usually means the opposite: the models
  answer about equally well, so cost and speed are deciding.

- **`arena watch`.** Re-evaluates a project and compares the fresh result
  against the mean of its own recent history, flagging a real composite move
  or a status change. A configured `webhook` fires on drift; `--fail-on-drift`
  turns it into a CI gate; `--loop --interval` runs it as a long-lived process
  for anyone without their own scheduler. Being disqualified in every run is
  not itself drift — only a *change* in status is, so a steadily-failing model
  is not re-flagged every tick.
- **A published GitHub Action** (`.github/actions/agent-arena-eval`) that
  evaluates a project on a pull request and posts the leaderboard as a
  comment, updated in place on every push rather than duplicated. An optional
  `baseline` input (an `arena export --format json` file, typically from the
  base branch) adds a delta column. Dogfooded in this repo by
  `.github/workflows/pr-eval-demo.yml` against an offline mock-model project,
  so the action is proven in real GitHub Actions and not only in
  `tests/test_pr_comment_action.py`.
- **Pricing-catalog staleness detection.** `arena models` and `arena validate`
  warn when `model_cards.json`'s `as_of` is more than 90 days old — the
  roadmap's own "warn past 90 days" wording, given a name
  (`PriceBook.is_stale`) other code can reference.
- **`Dockerfile`, `.dockerignore`, `.devcontainer/devcontainer.json`.** The
  image defaults to `arena ui --host 0.0.0.0`, since binding loopback inside a
  container reaches nothing outside it; the Dockerfile's own comment says
  plainly what that means for anyone publishing the port. Verified end to end
  against the `2.0.0rc1` build on TestPyPI: the image builds, the CLI and the
  UI both run, and a project mounted at `/data/projects` is discovered.
- **CLI test coverage for the lifecycle commands** (`tests/test_cli_lifecycle.py`).
  `arena rm`, `export`, `providers`, `secrets`, `config`, `duplicate`,
  `archive`, `vacuum`, `label`, `runs`, `projects` and `env` had been added
  across earlier commits with only their service-layer logic tested — the
  argument parsing and confirmation prompts had never been exercised through
  `main()` itself.

### Changed

- `_rehydrate` moved from `web/api.py` into `core/runner.py`. Both a resumed
  run and the browser's what-if need it, and core may not import web.

- **A multi-page browser UI.** A sidenav shell (Evaluate / Reference /
  Configure) over Overview, Projects, Runs, Models, Scorers, Providers and a
  five-tab Settings section, plus a per-case grid showing every case against
  every model. Destructive actions fetch the server's `dry_run` plan, print
  exactly what will be removed, and require the name typed before anything
  irreversible — the pattern already recorded in AGENTS.md, now actually
  enforced in the interface.

  Built in **vanilla JS**, revisiting the React + FastAPI plan approved
  earlier. With the API finished at 27 tested routes the remaining work was
  wiring rather than architecture, and vanilla keeps invariant 2 intact:
  `pip install agent-arena` still ships a working UI with no extra
  dependency, no npm, and no build step.
- **Browser UI/UX design overhaul**:
  - Multi-font hierarchy pairing `Plus Jakarta Sans` for headings, `Inter` for interfaces, and `JetBrains Mono` for benchmark scores and code.
  - Sidenav overhaul with theme switch shortcut in footer (`Dark | Settings`), clean divider, and active navigation indicators.
  - Interactive visual theme selector cards (`System`, `Light`, `Dark`) with OS window wireframes, live preview switching, and synchronized settings persistence.
  - Card-based settings sections (`Theme & Appearance`, `Workspace & Navigation`, `CLI Engine & Automation`) with responsive 2-column/3-column grids, animated iOS/Linear-style toggle switches, input path badges, and unit suffixes (`trials`, `workers`, `seconds`, `retries`, `temp`, `tokens`, `$`).
  - Models catalog table split into Available & Ready vs Needs API Key with green/yellow status indicators and instant text filtering.
  - Runs stream interface with status filters, clean text status badges, and cleaner timestamps.
  - Overview dashboard refined with horizontal breathing room and multi-column organization.
- **Provider routes over HTTP** (`GET`/`POST /api/providers`, `DELETE`,
  `/test`, `/discover`) — provider management had been CLI-only, and a
  Providers page without a working "Test connection" button is not worth
  having.

### Fixed

- `[hidden]` did not hide. A class rule setting `display` beats the user
  agent's `[hidden] { display: none }`, so the modal overlay rendered
  permanently over every page. Fixed globally rather than per-element, since
  the toast had the same latent bug.
- Static assets were served `max-age=60`, so an upgrade could pair a fresh
  `app.js` with a cached `app.css` and render a subtly broken page for a
  minute. They are now `no-store`, and the asset URLs carry the running
  version so both refetch together.
- `_last_run` never returned the run's cost, so the overview's spend column
  would have been permanently empty.
- `NotFoundError` from the service layer fell through to a generic HTTP 400,
  making "no such provider" indistinguishable from "malformed provider" while
  the project and run routes already answered 404. It now maps to 404, and
  `ConflictError` to 409.
- Fixed nested defaults settings binding in `web/static/app.js` (`defaults.*`) to
  prevent unknown parameter rejection errors on save.
- Fixed horizontal dropdown width in settings forms with constrained max-width
  and balanced grid layouts.

## [2.0.0rc1] - 2026-09-03

First release candidate. Published to TestPyPI only.

### Added

- `LICENSE` (MIT), `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, a PR
  template and `CODEOWNERS`.
- A PyPI release workflow using Trusted Publishing (OIDC, no stored token). Its
  verify job installs the built wheel into a clean venv and scaffolds and runs a
  project from it, because package-data omissions are the classic release bug in
  this layout.
- **Run and project lifecycle.** `arena projects`, `runs`, `label`, `archive`,
  `duplicate`, `rm`, `vacuum` and `env`, and the matching HTTP routes including
  the first `DELETE` verbs the product has ever had. Every destructive operation
  takes `dry_run` and returns the same plan either way, so a confirmation cannot
  misdescribe what it is about to do. A non-interactive shell without `--yes`
  refuses rather than assuming yes.
- **Run cancellation.** `POST /api/jobs/{id}/cancel` stops a sweep that is
  spending money. The runner checks between calls, keeps the results already
  collected, and labels them partial.
- **Budget enforcement.** `budgets.max_run_usd` and `max_model_usd` stop a run
  when the cap is crossed; `on_exceed: warn` records it without stopping.
- **Named provider profiles** under `providers:` — two API keys for the same
  vendor in one run, gateways with custom headers, a private CA, a proxy and
  model-prefix rewriting. The runner routes through them; asserted against a
  recording server rather than against the config object, because a config
  field that parses and changes nothing is the worst state for one to be in.
- **Export** — `arena export` and `GET /api/projects/{name}/export` write a run
  as CSV, JSON, markdown or HTML. The HTML is a single self-contained file with
  no CDN and no script, so it opens offline on a locked-down laptop.
- **`arena providers`, `arena secrets`, `arena config`.** A literal key passed
  to `providers add` is moved into the OS keyring and only the reference reaches
  `settings.json`.
- **Credential references** — `${env:}`, `${keyring:}`, `${file:}`, `${cmd:}` —
  and a `Secret` type whose `repr` and `str` are `***`. The OS keyring is
  reached through the platform tool rather than a Python dependency.
- **User settings** at `~/.config/agent-arena/settings.json`, written atomically
  at mode 0600, plus `GET`/`PUT /api/settings`.
- `.env` loading, wired into every command. Real environment variables win.
- Cross-vendor prices for OpenAI, Gemini and Mistral. Models whose current list
  price could not be sourced are omitted rather than estimated.
- A documentation tree of 51 pages across architecture, security, design,
  testing, reference, guides, operations and roadmap.

### Changed

- Store schema version 2: `deleted_at`, `archived_at` and `tags` on `runs`, with
  an idempotent migration runner driven by sqlite's `user_version`. Every read
  path excludes soft-deleted runs unless `include_deleted` is passed.
- Retry now distinguishes terminal from retryable failures — a 401 fails once
  instead of sleeping three times — and adds full jitter and `Retry-After`
  support.
- `arena ui` retains at most 50 finished jobs. It previously only ever inserted.
- Archiving a project now actually hides it from the default listing.
- The credential primitives moved from `service.secrets` to `core.secrets`, so
  the connector registry can resolve a profile's key without importing
  `service` — which would have been a cycle and would have pointed the
  dependency arrow backwards. `service.secrets` re-exports them and keeps the
  management side. `SecretError` joins the hierarchy in `core.errors`.

### Security

- A non-`GET` request carrying an `Origin` from another site is refused. The
  Host allow-list stops DNS rebinding but not a plain cross-site form POST,
  which carries a legitimate Host header.
- A request with no `Host` header is refused rather than allowed.

### Fixed

- A `JobManager` leak that grew unbounded for the life of an `arena ui` process.
- Eight concurrent workers retrying a rate limit in lockstep.
- Cost silently dropping out of a cross-vendor leaderboard because the catalog
  priced only Anthropic models.


## 1.0.0 — 2026-09-02

First stable release. The engine, the browser UI, pipeline targets and the
documentation site are all in place, and the public interfaces below are now
covered by semantic versioning.

### What it does

Agent Arena answers one question about *your* project: **which model — or which
pipeline architecture — should you actually ship, and what does that choice
cost?** Public benchmarks rank models on someone else's task against criteria
you did not choose. This ranks them on your test cases, your accuracy floor,
your budget and your latency ceiling, and refuses to recommend anything that
cannot clear your hard constraints.

### Added

- **Config-driven evaluation engine.** A project is a folder — `config.yaml`
  plus `tests.yaml` — with no second code path and no plugin to write. Ten
  built-in scorers (`classification`, `exact_match`, `contains`, `regex`,
  `numeric`, `json_match`, `semantic`, `code_exec`, `llm_judge`, `manual`),
  project-local scorers, and `pre_request` / `post_process` / `on_result` hooks.
- **A weighted composite with hard constraints.** Weight accuracy, cost and
  latency to match how your product actually works; a model that misses a floor
  is `DISQUALIFIED` with the reason printed rather than quietly ranked below the
  ones you can ship.
- **Honest resolution.** When the top two are within 0.02 the report says the
  sweep cannot separate them and asks for more cases, instead of implying a
  twelve-case run settled it.
- **Providers**: Anthropic, OpenAI, Gemini, LiteLLM, any OpenAI-compatible local
  endpoint (Ollama, vLLM, LM Studio), and deterministic `mock:` models so a
  whole project runs offline with no API key.
- **`arena ui`** — the same engine from a browser, for the people who set the
  budget but do not write YAML. A wizard that asks what job the AI is doing in
  plain language, results written as sentences instead of scores, and *what-if
  sliders* that re-rank from answers already collected with no new model calls.
  Stdlib-only: no Flask, no npm, no CDN.
- **Pipeline targets** — `run: pipelines/rag.py:answer` puts a whole multi-agent
  system on the same leaderboard as a single model call, graded and disqualified
  by exactly the same machinery. A target may report its own end-to-end spend and
  custom metrics, which are trusted over the price catalog.
- **Four example projects**, all offline: `support_triage`, `doc_extraction`,
  `local_demo`, and `pipeline_demo` (three architectures compared on one task).
- **Results database.** Every call lands in SQLite alongside the Markdown and
  JSON reports, so `arena history` can track regressions across runs.
- **The multi-agent handoff study**, frozen and reproducible: a 28-run sweep
  showing that splitting a task across agents loses information at the handoff
  independently of model capability.
- **Documentation site** at
  [adityamhaske.github.io/agent-arena](https://adityamhaske.github.io/agent-arena),
  rendered from this repository's own markdown so it cannot go stale, with a
  build-time link checker that fails on any broken internal link.

### Stability

From 1.0.0, these are the public surfaces covered by semantic versioning:

| Surface | Covered |
|---|---|
| `arena` CLI commands, flags and exit codes | yes |
| `config.yaml` / `tests.yaml` schema | yes |
| `Scorer`, `ScoreResult`, `ScoringContext` | yes |
| `Connector`, `GenerationRequest`, `GenerationResult` | yes |
| Hook signatures | yes |
| `run()`, `ArenaRunner`, `ProjectConfig` | yes |
| SQLite schema | additive changes only |
| `agent_arena.web.*` internals | no — the UI's HTTP API may change |
| `studies/multi_agent_handoff/` | no — frozen research code |

### Requirements

Python 3.10+. PyYAML is the only runtime dependency, and even that is optional —
JSON config and test files work without it. Every provider SDK imports lazily,
so you install only what you actually call.
