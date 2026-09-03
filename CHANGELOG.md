# Releases

All notable changes to Agent Arena. This file is the source for the
[Releases page](https://adityamhaske.github.io/agent-arena/releases/) on the
documentation site — the page is rendered from this file, so publishing a
release means editing here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.0.0] - unreleased

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
