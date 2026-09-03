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
| `export`, `secrets`, `providers`, `config` | Shipped |
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
| `providers:` routing | Shipped | The runner resolves a profile and applies its endpoint, credential, headers, TLS setting, proxy, timeout and model-prefix rewrite. Two accounts on one vendor compete in one run |
| `budgets:` enforced during a run | Shipped | `max_run_usd` and `max_model_usd` stop the sweep; `on_exceed: warn` does not |
| Secret references `${env:}` `${keyring:}` `${file:}` `${cmd:}` | Shipped | Resolved by the connector registry when a profile declares one; `arena secrets` manages them |
| OS keyring storage | Shipped | `arena secrets set/get/rm`; a literal key typed into `arena providers add` is moved into the key store and only the reference is persisted |
| `.env` loading | Shipped | Loaded in `cli.main()` before any command; real environment variables win |
| User settings at `~/.config/agent-arena` | **Partial** | `service/settings.py` is complete; nothing reads it |
| Per-provider rate limits | Planned | Parsed, never applied |
| User settings surface | Shipped | `arena config get/set/reset`, and `GET`/`PUT /api/settings` |

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
| `service/providers.py` — profile CRUD, health check, discovery | Shipped |
| `service/export.py` — CSV/JSON/markdown/HTML | Shipped |

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
| 574 tests, offline, ~28s | Shipped |

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

**The engine and the CLI are feature-complete for 2.0; the browser UI is not.**

Everything the v2 plan called a gap in the engine has closed: delete,
cancellation, budget enforcement, provider routing, secret references, export.
All of it works from the CLI and the HTTP API, and all of it is tested.

What has not been built is the *interface* on top: the sidenav shell, the
settings pages, and the per-case run detail view. The API those pages would
call exists — `GET`/`PUT /api/settings`, the delete and export routes, job
cancellation — but the eight-route hash-based UI does not use any of it yet.

Two smaller things remain in the engine: `evaluate --resume`, and the
statistics work (confidence intervals, paired comparison, power analysis).
