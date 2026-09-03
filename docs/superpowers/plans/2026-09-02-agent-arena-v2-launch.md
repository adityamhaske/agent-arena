# Agent Arena v2.0 — Ground-Up Redesign & Public Launch Plan

**Status:** awaiting confirmation · **Target version:** 2.0.0 · **Written:** 2026-09-02
**Complexity:** Large (~26–35 focused working days solo)

> **For agentic workers:** implement task-by-task with `superpowers:executing-plans` or
> `superpowers:subagent-driven-development`. Every phase ends green and independently
> releasable. Steps use `- [ ]` for tracking.

---

## 1. Requirements restated

Take Agent Arena from "a good engine with a thin front end" to a product an engineer
finds on GitHub, installs, and keeps. Concretely:

1. **Launch-ready as open source** — the legal, packaging, and first-impression work
   that decides whether anyone gets past the README.
2. **Deep customization** — local models, custom gateways, several API keys for the
   same vendor, per-provider rate limits and retries, secret references, budgets.
3. **A real application** — sidenav shell, ~12 pages, settings with sub-pages,
   history, and full object lifecycle including **delete** everywhere.
4. **Production hardening** — cancel a run, cap spend, resume an interrupted sweep,
   survive rate limits, never leak a key.
5. **Designed from the ground up**, not bolted on.

### Confirmed architectural decisions

| Decision | Choice |
|---|---|
| UI stack | **Split.** Core stays stdlib-only; `agent-arena[ui]` adds FastAPI + a **pre-built** React bundle shipped in the wheel. No npm for end users. |
| Deploy model | **Local-first, single user.** No accounts. OS keyring for secrets. Opt-in `--host 0.0.0.0 --token` for LAN/Codespaces. |
| Compatibility | **2.0, additive.** Every v1 `config.yaml` keeps working. New capability arrives as new optional blocks. `arena migrate` is opt-in. |

---

## 2. Honest assessment of what exists today

Verified by reading the code and running the suite — not from the README.

### What is genuinely good and must not be damaged

| Evidence | Why it matters |
|---|---|
| `pytest -q` → **282 passed in 11.85s**, fully offline, no provider SDK | A rare, real safety net. It is the license to refactor aggressively. |
| [`core/metrics.py`](../../../agent_arena/core/metrics.py) — 628 lines | Weighted composite, four normalization modes, hard-constraint `DISQUALIFIED` with printed reason, and a "too close to call" guard. This logic is the product. |
| [`core/config.py`](../../../agent_arena/core/config.py) — 650 lines | Every parse error points at the offending config line. Rare discipline. |
| [`connectors/registry.py`](../../../agent_arena/connectors/registry.py) | Provider inference by prefix with a clean explicit override path. |
| [`core/store.py`](../../../agent_arena/core/store.py) | Every call persisted to SQLite. All of Phase 6's statistics are already sitting in that table. |
| `pricing.py` refuses to guess a price | Invariant #4 ("never fabricate a number") is actually enforced in code. |

**The engine is not the problem.** Reach and lifecycle are.

### Verified gaps — grounded, not speculative

| # | Finding | Evidence | Severity |
|---|---|---|---|
| G1 | **No `LICENSE` file** although `pyproject.toml` declares `license = { text = "MIT" }` | `ls LICENSE` → not found | **Blocker.** No corporate legal team clears a dependency with no license text. |
| G2 | No `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, PR template | `ls` → none exist | High — GitHub shows "community standards" gaps on the repo page. |
| G3 | Not published to PyPI; no release workflow | `.github/workflows/` holds only `ci.yml`, `pages.yml` | High — `pip install agent-arena` fails for every reader of the README. |
| G4 | **Zero delete anywhere.** No `DELETE` route exists | `build_routes()` in [`web/server.py`](../../../agent_arena/web/server.py) lists 11 routes: GET/POST/PUT only | High — a project created by a typo is permanent. |
| G5 | **No run cancellation** | `JobManager` has `start`/`get`/`active_for`; no `cancel` | **High — money.** A misconfigured sweep against a paid API cannot be stopped from the browser. |
| G6 | **No settings surface at all**; API keys come only from `os.environ` | `grep -rn "dotenv\|\.env" agent_arena/` → no matches | High — launching the UI from a desktop icon sees none of the keys in your shell profile. |
| G7 | **Price catalog is Anthropic-only**: 11 models + `local` + `mock`, `as_of: 2026-06-24` | `model_cards.json` | **High.** Comparing `gpt-4o` against `claude-sonnet-5` — the flagship use case — silently drops the cost axis for both, because `raw["cost"]` is `None` unless *every* call is priced (`metrics.py:196`). |
| G8 | `JobManager._jobs` is never evicted | `web/api.py:161–193` — `start()` only inserts | Medium — every run leaks a `Job` plus up to 40 buffered results for the process lifetime. |
| G9 | Retry has **no jitter**, ignores `Retry-After`, and **retries non-retryable errors** | `runner.py:510–521` catches bare `Exception` and sleeps `backoff * 2**attempt` | Medium — 8 concurrent workers retry in lockstep, and a `401` costs three sleeps before failing. |
| G10 | Progress is **polled**, not streamed | `job_status` + client `setTimeout` | Medium — laggy, wasteful, and can't carry structured events. |
| G11 | **No resume.** An interrupted sweep is lost | no `--resume` in `cli.py` | Medium — a 45-minute run dying at 90% starts over and re-spends. |
| G12 | UI is 8 hash routes behind a 2-link topbar | `app.js:89–98` | This is the "looks very basic" the request names. |
| G13 | `web/api.py` (904 lines) re-implements project CRUD the CLI cannot reach | `_clean_models`, `_build_config`, `_write_structured` are UI-private | **Root cause of G4/G6.** Capability is trapped in the HTTP layer. |

**G13 is the architectural finding.** Everything the UI can do that the CLI cannot —
and vice versa — traces to there being no shared use-case layer. Fix that first and
every later feature lands in CLI + HTTP + Python at once, for free.

---

## 3. Target architecture

### 3.1 Layering

```
   arena CLI          FastAPI (agent_arena/webui)        import agent_arena
   argparse           pydantic · OpenAPI · SSE           Python API
        │                        │                             │
        └────────────────────────┼─────────────────────────────┘
                                 ▼
                    agent_arena/service/          ◄── NEW. stdlib. no HTTP.
       projects · runs · secrets · providers · settings · catalog · export
                                 │
   ┌──────────┬──────────┬───────┴────┬─────────────┬────────────┐
   ▼          ▼          ▼            ▼             ▼            ▼
 config     runner    metrics       store      connectors    scorers
                        (agent_arena/core — unchanged, stdlib-only)
```

**Rule that keeps this honest: nothing may be UI-only.** A capability lands in
`service/`, and the CLI and HTTP layers are both thin adapters over it. The
CLI-only install stays feature-complete, which is what makes the `[ui]` extra a
genuine choice rather than a tax.

### 3.2 Packaging

```
pip install agent-arena          # engine + CLI. pyyaml only. UNCHANGED.
pip install agent-arena[ui]      # + fastapi, uvicorn. React bundle is prebuilt in the wheel.
pip install agent-arena[all]     # + every provider SDK
uvx --from 'agent-arena[ui]' arena ui     # zero-install trial
```

```
agent_arena/            stdlib engine + CLI + service layer      (no new deps)
agent_arena/webui/      FastAPI app
agent_arena/webui/dist/ committed build output — served as static files
ui/                     React + Vite + TS source. Built in CI. Not shipped as source.
```

CI rebuilds `ui/` and fails if `agent_arena/webui/dist/` differs from the build —
so the committed bundle can never silently drift from its source.

**Invariant rewrite for `AGENTS.md`:** #1 stays verbatim (the engine is stdlib-only,
and a CI job proves it). #2 becomes: *"the default install adds no dependency; the UI
is an opt-in extra whose assets are prebuilt — a user never runs npm."* #3 is
unchanged and now enforced by the service layer: rankings come from
`build_leaderboard`, and the UI only re-words them.

---

## 4. The customization spine — `providers:`, secrets, budgets

This is the heart of the request. Today a model entry carries `api_base` and
`api_key_env` inline, which makes the common cases impossible: two API keys for the
same vendor in one run, a corporate gateway with required headers, per-endpoint rate
limits.

### 4.1 Named provider profiles (new, optional block)

```yaml
providers:
  - id: work_openai
    kind: openai
    base_url: https://api.openai.com/v1
    api_key: ${env:OPENAI_API_KEY}
    headers: { OpenAI-Organization: org-123 }
    timeout_s: 60
    rate_limit: { rpm: 500, tpm: 200000, concurrency: 4 }
    retry: { attempts: 3, backoff_s: 1.0, jitter: true, respect_retry_after: true }

  - id: personal_openai            # same vendor, different account, same run
    kind: openai
    api_key: ${keyring:agent-arena/openai-personal}

  - id: corp_gateway               # LiteLLM / Portkey / Cloudflare AI Gateway / Bedrock proxy
    kind: openai_compatible
    base_url: https://gateway.corp.internal/v1
    api_key: ${keyring:agent-arena/corp}
    headers: { X-Portkey-Config: cfg_abc }
    verify_tls: /etc/ssl/corp-ca.pem     # or false, loudly warned
    proxy: http://squid.corp:3128
    model_prefix: "openai/"              # rewrite ids on the way out

  - id: laptop
    kind: ollama
    base_url: http://localhost:11434/v1
    discover: true                       # enumerate /v1/models into the picker

  - id: cluster_vllm
    kind: openai_compatible
    base_url: http://10.0.0.5:8000/v1

models:
  - key: gpt5_work
    provider: work_openai                # by profile id, not by vendor kind
    model: gpt-5
  - key: gpt5_personal
    provider: personal_openai            # ← impossible in v1
    model: gpt-5
  - key: llama_local
    provider: laptop
    model: llama3.2
```

Back-compat: `provider:` resolving to a known *kind* (`anthropic`, `openai`, …) keeps
its v1 meaning. Only an id declared in `providers:` changes resolution. Existing
example projects are untouched.

### 4.2 Secret references — never a literal in config

| Scheme | Resolves from |
|---|---|
| `${env:NAME}` | process environment |
| `${keyring:service/account}` | OS credential store (Keychain / Credential Manager / Secret Service) |
| `${file:~/.secrets/openai}` | file contents, trimmed; refuses if mode is group/world-readable |
| `${cmd:op read op://vault/item/field}` | stdout of a command — 1Password, Vault, `aws secretsmanager` |
| *(unset)* | fall back to the vendor's conventional env var, as today |

Resolution order for a bare model with no explicit ref:
**explicit ref → keyring → `~/.config/agent-arena/secrets.json` (0600) → project `.env` → process env.**

**Redaction is a tested invariant.** Resolved secrets are wrapped in a `Secret` type
whose `__repr__`/`__str__` returns `"***"`. A test asserts no key appears in any
report, export, API response, log line, or error message — including a
`ConnectorError` echoing a request.

### 4.3 Budgets — spend caps that actually stop the run

```yaml
budgets:
  max_run_usd: 5.00
  max_model_usd: 2.00
  confirm_above_usd: 1.00       # UI/CLI asks before starting
  on_exceed: stop               # stop | warn
```

Estimated pre-flight (the `--dry-run` path already computes a plan), enforced live in
the runner, and on breach the run **stops with partial results preserved and clearly
labelled partial** — never silently truncated into a leaderboard.

### 4.4 Full customization matrix

| Surface | Knobs |
|---|---|
| **Provider** | kind · base_url · api_key ref · extra headers · TLS verify / custom CA · proxy · connect & read timeout · rpm / tpm / concurrency · retry attempts, backoff, jitter, `Retry-After` · model prefix/suffix rewrite · org & project ids · default params |
| **Model** | key · model id · provider ref · temperature, max_tokens, top_p, seed, stop, reasoning effort, thinking budget · per-model system prompt · card overrides (price, context, features) · enabled flag · tags |
| **Prompting** | global system · per-model system · per-case system · template with variables · few-shot block · raw message-list form |
| **Run** | trials · global and per-provider concurrency · timeout · retries · backoff · jitter · seed · shuffle · warmup · tag / id / limit filters · sample percentage · **resume** |
| **Scoring** | default scorer · per-case scorer · scorer options · extra scorer dirs · judge model, prompt & rubric · multi-scorer ensemble with per-scorer weight |
| **Metrics** | weight per metric · custom metrics emitted by scorers · normalization mode (`minmax`/`target`/`budget`/`raw`) · direction · budget · latency target · latency percentile (p50/p90/p95/p99) |
| **Constraints** | min_accuracy · max_latency_p95_ms · max_cost_per_1k_calls · required features · required privacy properties · min sample size |
| **Budgets** | max per run · max per model · confirm threshold · on-exceed behaviour |
| **Output** | formats (md / json / html / csv) · output dir · report template override · verbosity |
| **Storage** | db path · retention policy · auto-vacuum · archive-vs-delete |
| **Hooks** | existing `on_request` / `on_result` + new `on_run_start`, `on_run_end`, `on_error`, `on_budget_exceeded` |
| **UI** | theme · density · number format · currency · timezone · default landing page · visible columns · saved views and filters |
| **Profiles** | `arena --profile work` selects a provider set, so work and personal keys never mix |

---

## 5. Product surface — pages and lifecycle

### 5.1 App shell

```
┌────────────────┬──────────────────────────────────────────────┐
│ ◆ Agent Arena  │  breadcrumb                  ⌘K   ◐   v2.0.0 │
├────────────────┼──────────────────────────────────────────────┤
│  Overview      │                                              │
│  Projects      │                                              │
│  Runs          │                  page body                   │
│  Compare       │                                              │
│  Models        │                                              │
│  Providers     │                                              │
│  Test cases    │                                              │
│  Scorers       │                                              │
│  Settings      │                                              │
│  Docs          │                                              │
├────────────────┤                                              │
│ ● run active   │                                              │
│   42/120 · $0.31│                                             │
│   [Cancel]     │                                              │
└────────────────┴──────────────────────────────────────────────┘
```

### 5.2 Route inventory

| Route | Page | What it does |
|---|---|---|
| `/` | **Overview** | Recent runs across all projects, spend this week, regressions, provider health, quick actions |
| `/projects` | **Projects** | Grid/list, search, tag filter, duplicate, archive, **delete** |
| `/p/:id` | **Project** | Tabs: Setup · Cases · Models · Runs · Insights |
| `/p/:id/setup` | Setup | Form editor **and** raw YAML editor with live schema validation, side by side |
| `/p/:id/cases` | Cases | Table editor, inline edit, bulk tag, import CSV/JSONL, **bulk delete** |
| `/p/:id/models` | Models | Pick from provider catalog, per-model param overrides, price override, enable/disable |
| `/p/:id/runs` | Runs | This project's history, sparkline trend, regression flags |
| `/p/:id/insights` | Insights | What-if sliders, per-case discrimination, coverage, disagreement mining |
| `/runs` | **All runs** | Cross-project, filter by project/model/status/date/cost, **delete**, archive, export |
| `/runs/:id` | **Run detail** | Leaderboard with CIs · per-case × per-model grid · failure drill-down · raw output · cost breakdown · config snapshot · re-run |
| `/compare` | **Compare** | Run A vs Run B, or model vs model within a run. Diff view, per-case flips |
| `/models` | **Models catalog** | Every known model: price, context, features, `as_of` staleness banner, override editor |
| `/providers` | **Providers** | CRUD connection profiles · **Test connection** · discovered models · masked keys · **delete key** |
| `/cases` | **Case library** | Cross-project corpus, import, dedupe, coverage against tags |
| `/scorers` | **Scorers** | 10 builtins + project scorers, docs, **live tester** (paste output + reference → verdict) |
| `/settings/*` | **Settings** | 9 sub-pages, below |
| `/docs` | **Docs** | In-app, offline, rendered from the same markdown as the site |

### 5.3 Settings sub-pages

| Sub-page | Contents |
|---|---|
| General | Projects directory, default landing page, open browser on start, update check |
| **Providers & keys** | Add/edit/test/**delete** profiles · masked key display · keyring status · "reveal" behind an OS prompt |
| Defaults | trials, concurrency, timeout, retries, temperature, max_tokens for new projects |
| **Budgets & safety** | Spend caps, confirm threshold, global kill switch, "require confirmation for paid models" |
| Pricing catalog | View catalog, staleness warning, import a price file, per-model override, reset |
| **Storage & data** | DB size, run count, vacuum, export everything, retention policy, **delete all data** (typed confirm) |
| Appearance | Theme, density, number/currency/timezone format |
| Advanced | Feature flags, experimental scorers, raw settings JSON editor, log level, diagnostics bundle |
| About | Version, changelog, license, links, credits |

### 5.4 Lifecycle — the "delete option, everything" requirement

Every object gets **create · read · update · delete · duplicate · export · archive.**

| Object | Delete semantics |
|---|---|
| Project | Typed-name confirmation. Option: *keep results* (delete files, retain run rows). |
| Run | Soft delete → `runs.deleted_at`. Cascades to `results` + `rankings`. Report files removed. `arena vacuum` hard-deletes. |
| Test case | Immediate, undoable for 10s via toast. Bulk delete by filter or tag. |
| Provider profile | Deletes the profile **and** offers to purge its keyring entry. Warns which models reference it. |
| API key | Purged from keyring and secrets file. Never merely blanked in the UI. |
| All data | Settings → Storage. Typed confirmation. Lists exactly what will be destroyed first. |

**Rules.** Reversible actions get a 10-second undo toast. Irreversible ones require
typed confirmation and print what will be destroyed *before* asking. Archive is
distinct from delete: archived objects leave the default lists and stay queryable.
Every delete has a CLI mirror — `arena rm run <id>`, `arena rm project <name>` — each
supporting `--dry-run` and `--yes`.

---

## 6. Phases

Each phase ends with a green suite and is independently releasable.

### Phase 0 — Launch blockers · ~1 day · ships alone as v1.1

Nothing here depends on anything else, and the repo is not publishable without it.

- [ ] `LICENSE` — MIT, matching `pyproject.toml`'s existing declaration **(G1)**
- [ ] `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `CODEOWNERS` **(G2)**
- [ ] `.github/workflows/release.yml` — PyPI Trusted Publishing (OIDC, no stored token), TestPyPI dry run first **(G3)**
- [ ] README restructure: one-line what/why, a screenshot or GIF above the fold, a 60-second quickstart, badges (CI · PyPI · Python · license)
- [ ] Fix **G9** — classify errors as retryable vs not (`401`/`403`/`400` fail fast), add full jitter, honour `Retry-After`
- [ ] Fix **G8** — evict finished jobs after N minutes / cap at 50
- [ ] Add `.env` loading — a ~30-line stdlib parser, no `python-dotenv` **(G6)**
- [ ] Widen `model_cards.json` with OpenAI, Gemini, Mistral, DeepSeek, Groq, Bedrock prices; document the "sourced or absent, never guessed" contribution rule **(G7)**

### Phase 1 — Service layer extraction · 3–4 days

The refactor that unlocks everything else. Strangler pattern: move logic, leave
`web/api.py` as a thin adapter, keep 282 tests green at every commit.

- [ ] Create `agent_arena/service/{projects,runs,secrets,providers,settings,catalog,export}.py` (stdlib only)
- [ ] Move project CRUD out of `web/api.py`; generalize `_clean_*` / `_build_config` into a reusable, tested validator
- [ ] Add the missing verbs: `delete_project`, `duplicate_project`, `archive_project`, `delete_run`, `cancel_run`, `export_run`
- [ ] `RunController` with a cooperative cancel token threaded into `ArenaRunner` **(G5)**
- [ ] New CLI commands over the same service: `arena new`, `arena rm`, `arena ls`, `arena export`, `arena secrets`, `arena providers`, `arena cancel`
- [ ] `tests/test_service_*.py` — behaviour-named, offline, mirroring `tests/test_web.py`'s docstring convention

### Phase 2 — Providers, secrets, budgets · 4–5 days

- [ ] `ProviderSpec` parsed in `core/config.py`, mirroring `ModelSpec.parse`'s error style
- [ ] Secret resolver + `Secret` redaction type + a redaction test across reports, exports, API responses, and error strings
- [ ] `OpenAICompatibleConnector` unifying local / openai / gateway: headers, custom CA, proxy, model rewriting
- [ ] Per-provider token-bucket rate limiter (rpm/tpm/concurrency) in the runner's scheduler
- [ ] `budgets:` block — pre-flight estimate, live enforcement, graceful stop with partial results labelled
- [ ] Provider health check + `/v1/models` discovery → `arena providers test|list|discover`
- [ ] `arena migrate` — opt-in rewrite of inline `api_base`/`api_key_env` into `providers:`

### Phase 3 — Data model & lifecycle · 2–3 days

- [ ] Store schema v2: `archived_at`, `deleted_at`, `label`, `notes`, `tags`, `config_snapshot`, `git_sha` on `runs`; new `run_events` table for the SSE feed
- [ ] Versioned, idempotent stdlib migration runner + `arena migrate --db`
- [ ] Cascading delete, `arena vacuum`, retention policy
- [ ] Resumable runs — per-call idempotency key `(run_id, model_key, test_id, trial)`; `arena evaluate --resume <run_id>` skips completed cells **(G11)**
- [ ] Export: CSV, JSON, self-contained HTML report

### Phase 4 — New UI: shell + core pages · 5–7 days

- [ ] `ui/` — Vite + React + TS. Design tokens, a small in-house component set (no heavyweight kit), light/dark, 320px→2560px
- [ ] `agent_arena/webui/` — FastAPI, pydantic request/response models replacing the hand-rolled `_clean_*` validators, OpenAPI at `/api/docs`
- [ ] **SSE** run stream replacing polling; typed events `run_start`, `call_complete`, `budget_warning`, `run_end` **(G10)**
- [ ] `--token` bearer mode for non-loopback binds; keep the existing DNS-rebinding host allow-list and CSP from `server.py`
- [ ] Shell: sidenav, command palette (⌘K), toasts with undo, empty states, keyboard shortcuts, error boundaries
- [ ] Pages: Overview, Projects, Project (5 tabs), Runs, Run detail with the per-case grid, all 9 Settings sub-pages
- [ ] Build pipeline: `npm run build` → `agent_arena/webui/dist/`, committed; CI rebuilds and diffs to prove no drift
- [ ] `arena ui` detects the missing extra and prints the exact install command

### Phase 5 — Depth pages · 3–4 days

- [ ] Compare (run↔run, model↔model, per-case flip diff)
- [ ] Models catalog with `as_of` staleness banner and override editor
- [ ] Providers page with live connection test and model discovery
- [ ] Case library: CSV/JSONL import, dedupe, coverage-by-tag, **disagreement mining** (the store already holds every model's answer to every case)
- [ ] Scorers page with a live tester
- [ ] In-app docs rendered from the repo's markdown — same source as the site, so they cannot drift

### Phase 6 — Statistical credibility · 2–3 days *(roadmap item 3)*

- [ ] Bootstrap confidence intervals over **test cases**, not trials — cases are the unit of generalisation
- [ ] Paired comparison — every model sees identical cases, so the pairing is guaranteed and far more sensitive than independent means
- [ ] Power calculation: *"separating your top two at 95% confidence needs ~40 more cases"*
- [ ] Per-case discriminative value — which cases actually separate the leaders
- [ ] Error bars in the UI and one plain sentence: *"On this evidence these two are indistinguishable."*
- [ ] Stdlib `statistics` + `random` only. Offline-testable against mock models.

### Phase 7 — Continuous + ecosystem · 3–4 days *(roadmap item 4)*

- [ ] `arena watch` — scheduled re-run, alert when a model leaves its historical band
- [ ] A published GitHub Action that runs the arena on PRs touching prompts/pipelines and comments the leaderboard delta, gated by the existing `--fail-under`
- [ ] Provider-change detection via the model card's `as_of`
- [ ] Docker image, devcontainer, `uvx` one-liner
- [ ] Docs site: new pages for providers, settings, statistics, and the UI, plus screenshots

### Phase 8 — Launch · ~2 days

- [ ] v2.0.0 — changelog, version bumped in `pyproject.toml` **and** `agent_arena/__init__.py` (they must match), tag, GitHub release, PyPI
- [ ] A 3-minute demo GIF and a comparison table against promptfoo / LangSmith / Braintrust / Inspect, honest about where each is stronger
- [ ] Seeded `good-first-issue` set and a public roadmap board

---

## 7. Patterns to mirror — do not invent new ones

| Category | Source | Pattern to follow |
|---|---|---|
| CLI naming | `cli.py:123` `cmd_evaluate` | `cmd_<verb>` per subcommand; `_private` module helpers |
| Errors | `core/errors.py:9` | `ArenaError` base, one subclass per subsystem, message points at the offending config line |
| User-facing errors | `web/language.py` `plain_error` | Raw error → plain sentence. The UI never shows a traceback. |
| HTTP errors | `web/api.py:78` `ApiError(ArenaError)` | Carries an HTTP status alongside the message |
| Data access | `core/store.py:102` | Context-manager store, raw SQL, `CREATE TABLE IF NOT EXISTS`, explicit indexes |
| Extension contracts | `scorers/base.py` | ABC + result dataclass + registry with a `register_*` function |
| Lazy dependencies | `connectors/providers.py:35` `_require` | Import inside the method; the error names the exact pip extra |
| Config parsing | `core/config.py` `ModelSpec.parse` | `@classmethod parse(raw, index)` raising `ConfigError` with position |
| Tests | `tests/test_web.py:1` | Module docstring states *why* these tests exist; names describe behaviour; fully offline |
| Docs | `site/build.py` `PAGES` | A site page renders an existing repo markdown file; adding a page is one line |

**No logging framework exists today** (the CLI uses `print`, `server.py` suppresses
request logs). Phase 1 introduces a single stdlib `logging` logger under
`agent_arena`, with a `NullHandler` by default so library use stays silent and
`--verbose` turns it on. Do not reach for a third-party logger.

---

## 8. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `arena ui` regresses — the UI now needs the `[ui]` extra where today it just works | High | Medium | `arena ui` detects the missing extra and prints the one-line install. CLI stays feature-complete. If adoption suffers, the React bundle is static — it can move into the base wheel later without redesign. |
| Committed `dist/` drifts from `ui/` source | Medium | High | CI rebuilds and `git diff --exit-code`s the bundle. A drifted bundle fails the build. |
| The service-layer refactor breaks the 282 tests | Medium | High | Strangler order: move logic, keep `web/api.py` signatures stable, run the suite every commit. The suite is 11.8s — run it constantly. |
| Secrets land on disk or in a report | Medium | **High** | Keyring first; `0600` fallback; `Secret` type whose repr is `***`; a test asserting no key appears in any report, export, response, or error string. |
| Stdlib purity erodes once FastAPI is in the repo | Medium | High | A CI job installs the base package only and asserts `import agent_arena` plus the full offline example sweep. Same discipline as today's "no provider SDK" job. |
| Scope creep across nine phases | High | Medium | Phase 0 ships alone. Every phase ends green and releasable. Phases 6 and 7 can slip past launch without weakening it. |
| Pricing catalog goes stale and misleads a decision | High | Medium | Surface `as_of` prominently, warn past 90 days, keep the "sourced or absent, never guessed" rule, make community price PRs a one-file change. |
| Rewriting the UI loses the plain-English layer, which is a genuine differentiator | Medium | High | `web/language.py` is engine-adjacent — port it into `service/`, keep its tests, and treat its sentences as product copy, not scaffolding. |

---

## 9. Validation

```bash
pip install -e ".[dev]" && pytest -q                     # 282+ green, offline, no provider SDK
pip install -e . && python -c "import agent_arena"       # stdlib purity gate
arena validate --project projects/support_triage
arena evaluate --project projects/support_triage --quiet --no-report
arena evaluate --project projects/doc_extraction  --quiet --no-report
arena evaluate --project projects/pipeline_demo   --quiet --no-report
arena init /tmp/scaffold --name scaffold_check && arena evaluate --project /tmp/scaffold --quiet --no-report
python site/build.py && python site/check_links.py
cd ui && npm ci && npm run build && npm test
git diff --exit-code agent_arena/webui/dist              # bundle matches its source
```

---

## 10. Acceptance — the definition of "launch ready"

- [ ] `pip install agent-arena` works from PyPI and `arena evaluate --project ...` produces a leaderboard with no API key
- [ ] `LICENSE` present; GitHub's community-standards checklist is complete
- [ ] A stranger reaches a real leaderboard within 60 seconds of landing on the README
- [ ] Every object can be created, edited, duplicated, exported, and **deleted** — from both the UI and the CLI
- [ ] A run can be cancelled mid-flight, and a budget cap stops it automatically
- [ ] Two API keys for the same vendor, a corporate gateway, and a local Ollama model all compete in one run
- [ ] No secret appears in any report, export, log, API response, or error message (asserted by test)
- [ ] `pytest -q` green on Python 3.10–3.13 with no provider SDK installed
- [ ] The four example projects still validate and run offline in CI
- [ ] A leaderboard whose top two are statistically indistinguishable says so, in a sentence
