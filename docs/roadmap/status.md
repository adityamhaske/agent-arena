# Status: shipped, partial, planned

Derived from the code and `git log`, not from the plan. If a row here disagrees
with a claim elsewhere in the documentation, this page is right.

Legend: **Shipped** works end to end · **Partial** exists but is not reachable
from a normal workflow · **Planned** designed, not built.

Last updated for the commit that added the run and project lifecycle.

## Core engine

| Capability | Status | Notes |
|---|---|---|
| Config-driven projects (`config.yaml` + `tests.yaml`) | Shipped | |
| Ten builtin scorers | Shipped | `arena scorers` |
| Custom scorers from a project's `scorers/` | Shipped | |
| `hooks.py` pre-request and post-process | Shipped | |
| Six connectors | Shipped | anthropic, openai, gemini, litellm, local, mock |
| `run:` pipeline targets | Shipped | `projects/pipeline_demo` |
| Weighted composite, four normalization modes | Shipped | |
| Hard constraints → `DISQUALIFIED` | Shipped | |
| Resolution guard ("too close to call") | Shipped | |
| SQLite storage of every call | Shipped | |
| Markdown and JSON reports | Shipped | |
| Trials, concurrency, timeouts | Shipped | |
| Retry: terminal vs retryable, jitter, `Retry-After` | Shipped | `core/retry.py` |
| Cross-vendor pricing | Shipped | OpenAI, Gemini, Mistral, Anthropic |
| Regression tracking across runs | Shipped | `arena history` |

## CLI

| Command | Status |
|---|---|
| `evaluate` / `run`, with `--models --trials --tags --ids --limit --dry-run --fail-under --json` | Shipped |
| `report`, `history`, `init`, `models`, `scorers`, `tests`, `validate`, `ui` | Shipped |
| `projects`, `runs`, `rm`, `duplicate`, `archive`, `vacuum`, `label`, `env` | Shipped |
| `export`, `secrets`, `providers`, `config` | Planned |
| `watch` | Planned |
| `--resume` | Planned |

## Browser UI

| Capability | Status | Notes |
|---|---|---|
| Local server, stdlib only, loopback | Shipped | |
| Five-step wizard | Shipped | |
| Plain-English results | Shipped | `web/language.py` |
| What-if sliders, no new spend | Shipped | |
| Live run progress with an output feed | Shipped | Polled, not streamed |
| Eight hash routes | Shipped | |
| Job retention cap | Shipped | 50 finished jobs |
| Cancel a running sweep | Shipped | The runner checks the cancel event between calls; partial results are kept and labelled partial |
| Delete a project or a run | Shipped | `DELETE` routes, with `dry_run` and `keep_results` |
| Duplicate, archive, label, vacuum | Shipped | |
| Settings read/write over HTTP | Shipped | `GET`/`PUT /api/settings` |
| Settings pages in the browser | Planned | The API exists; no UI is built on it |
| Sidenav, 16 routes | Planned | |
| Compare, Models, Providers, Cases, Scorers pages | Planned | |
| Server-sent events instead of polling | Planned | |
| Token-authenticated non-loopback mode | Planned | |

## Configuration and credentials

| Capability | Status | Notes |
|---|---|---|
| API keys from environment variables | Shipped | |
| `providers:` block parses; profiles resolve | **Partial** | `ProjectConfig.provider_for()` works and is tested. **The runner does not route through a profile** — headers, custom CA, proxy and model-prefix rewriting are not yet applied to a call |
| `budgets:` enforced during a run | Shipped | `max_run_usd` and `max_model_usd` stop the sweep; `on_exceed: warn` does not |
| Secret references `${env:}` `${keyring:}` `${file:}` `${cmd:}` | **Partial** | `service/secrets.py` is complete and tested. **Nothing calls it yet** — no CLI command and no runner path |
| OS keyring storage | **Partial** | Implemented; not reachable from any command |
| `.env` loading | Shipped | Loaded in `cli.main()` before any command; real environment variables win |
| User settings at `~/.config/agent-arena` | **Partial** | `service/settings.py` is complete; nothing reads it |
| Per-provider rate limits | Planned | Parsed, never applied |

The pattern in that table is worth stating plainly: the v2 foundation is built
and tested, and almost none of it is *connected*. The wiring — CLI commands, HTTP
routes, and runner integration — is the next piece of work.

## Service layer

| Module | Status |
|---|---|
| `service/errors.py`, `service/__init__.py` | Shipped |
| `service/secrets.py` | Shipped (unconsumed) |
| `service/settings.py` | Shipped (unconsumed) |
| `service/paths.py` — containment checks for caller-supplied names | Shipped |
| `service/projects.py` — list, describe, duplicate, archive, delete | Shipped |
| `service/runs.py` — list, get, delete, restore, archive, label, vacuum | Shipped |
| Store schema v2 — soft delete, migration runner | Shipped |
| `service/providers.py` — profile CRUD, health check, discovery | Planned |
| `service/export.py` — CSV/JSON/markdown/HTML | Planned |

## Project health

| Item | Status |
|---|---|
| MIT `LICENSE` | Shipped |
| `SECURITY.md`, `CONTRIBUTING.md`, code of conduct, PR template, CODEOWNERS | Shipped |
| CI on Python 3.10–3.13 with no provider SDK | Shipped |
| Example projects verified in CI | Shipped |
| PyPI release workflow with wheel verification | Shipped |
| **Published to PyPI** | **Not yet** — the workflow is configured; no release has been tagged. Install from source |
| Documentation site | Shipped |
| 526 tests, offline, ~21s | Shipped |

## Statistics

| Capability | Status |
|---|---|
| Bootstrap confidence intervals | Planned |
| Paired comparison | Planned |
| Power calculation | Planned |
| Per-case discriminative value | Planned |

## Continuous evaluation

| Capability | Status |
|---|---|
| `arena watch` | Planned |
| GitHub Action | Planned — `--fail-under` works today in a plain workflow step |
| Provider-change detection | Planned |
| Docker image, devcontainer | Planned |

## If you only remember one thing

**Provider profiles and secret references still do not affect a real run.**
`providers:` parses, profiles resolve, and `${env:}` / `${keyring:}` /
`${file:}` / `${cmd:}` all work and are tested — but the runner does not yet
route a call through a profile, so headers, a custom CA, a proxy and
model-prefix rewriting are not applied, and credentials still come from
environment variables. That is the last large gap between what the code
contains and what the product does.

Everything else on the "not usable" list has closed. Delete, cancellation and
budget enforcement all work end to end, from both the CLI and the HTTP API.
