# Status: shipped, partial, planned

Derived from the code and `git log`, not from the plan. If a row here disagrees
with a claim elsewhere in the documentation, this page is right.

Legend: **Shipped** works end to end · **Partial** exists but is not reachable
from a normal workflow · **Planned** designed, not built.

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
| `rm`, `export`, `duplicate`, `archive`, `vacuum`, `label` | Planned |
| `secrets`, `providers`, `config`, `env` | Planned |
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
| Cancel a running sweep | **Partial** | `ArenaAPI.cancel_run` and the job cancel event exist; the runner has **no cooperative check**, so a sweep cannot actually be stopped |
| Delete anything | Planned | **Zero `DELETE` routes exist today** |
| Settings pages | Planned | |
| Sidenav, 16 routes | Planned | |
| Compare, Models, Providers, Cases, Scorers pages | Planned | |
| Server-sent events instead of polling | Planned | |
| Token-authenticated non-loopback mode | Planned | |

## Configuration and credentials

| Capability | Status | Notes |
|---|---|---|
| API keys from environment variables | Shipped | |
| `providers:` block parses; profiles resolve | **Partial** | `ProjectConfig.provider_for()` works and is tested. **The runner does not route through a profile** — headers, custom CA, proxy and model-prefix rewriting are not yet applied to a call |
| `budgets:` block parses and validates | **Partial** | `BudgetSettings` exists. **The runner does not enforce a cap** |
| Secret references `${env:}` `${keyring:}` `${file:}` `${cmd:}` | **Partial** | `service/secrets.py` is complete and tested. **Nothing calls it yet** — no CLI command and no runner path |
| OS keyring storage | **Partial** | Implemented; not reachable from any command |
| `.env` loading | **Partial** | `core/env.py` is complete and tested. **Not wired into `cli.main()`**, so it has no effect on a real run |
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
| `service/projects.py` — project CRUD, duplicate, archive, delete | Planned |
| `service/runs.py` — list, delete, archive, label, vacuum | Planned |
| `service/providers.py` — profile CRUD, health check, discovery | Planned |
| `service/export.py` — CSV/JSON/markdown/HTML | Planned |
| Store schema v2 — soft delete, migrations | Planned |

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
| 472 tests, offline, ~12s | Shipped |

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

Three capabilities described elsewhere in these docs are **not usable yet**, and
each is easy to assume works because the code exists:

1. **Delete.** There is no `DELETE` route and no `arena rm`. Nothing in the
   product can remove a project or a run.
2. **Cancellation.** The button would exist, but the runner never checks the
   flag, so a sweep spending money cannot be stopped.
3. **Provider profiles, secret references and `.env`.** All three parse, resolve
   and are tested — and none of them affect a real evaluation, because nothing
   calls them yet.
