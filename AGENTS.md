# AGENTS.md

Working notes for AI agents (and humans) contributing to Agent Arena. Read this
before changing anything; it records the decisions that are easy to break by
accident.

## What this repository is

Two independent systems that share a philosophy — *structured evidence over
vibes* — and answer opposite questions:

| | Question | What varies | Where |
|---|---|---|---|
| **Universal Arena** | Which model, or which pipeline, should my project ship? | the model / the architecture | `agent_arena/`, `projects/` |
| **Multi-agent study** | Does splitting a task across agents lose information? | the architecture | `studies/multi_agent_handoff/` |

They share no code. **Zero imports cross between them**, and that is deliberate —
do not add one.

## Invariants — breaking these is a bug, not a trade-off

1. **The engine is stdlib-only.** PyYAML is the single runtime dependency and
   even that is optional (JSON config works without it). Every provider SDK
   imports lazily, so `pip install agent-arena` pulls in nothing you did not ask
   for. The CI test job installs no provider SDK on purpose: if the suite ever
   needs `anthropic` present to pass, that invariant has been broken.
2. **The browser UI adds no dependency.** `agent_arena/web/` is `http.server`
   plus vanilla JS. No Flask, no npm, no CDN, no build step.
3. **The UI never re-implements the engine.** Rankings come from
   `core/metrics.build_leaderboard`; `web/language.py` only re-words them. If the
   UI and the CLI ever disagree about who won, the CLI is right and the UI has a
   bug.
4. **Never fabricate a number.** A model with no price gets no cost metric rather
   than a guessed one; a sweep that cannot separate two models says so. Honesty
   about resolution is the product.
5. **A project is a folder, not code.** `config.yaml` + `tests.yaml`. There is no
   second code path and no plugin system to extend.
6. **The example projects are documentation.** They run offline in CI. If they
   stop validating or running, the docs are lying.
7. **The dependency arrow points one way.** `agent_arena/service/` may import
   from `core/`, `connectors/` and `scorers/`. It may **never** import from
   `agent_arena/web/`, and nothing in it knows about HTTP status codes,
   argparse namespaces, or printing. This is what lets the CLI and the browser
   share one implementation instead of two that drift.
8. **A credential is never a `str`.** Resolved keys are wrapped in
   `service.secrets.Secret`, whose `__repr__` and `__str__` return `***`.
   `.reveal()` is the only way out, and its name is deliberately greppable. No
   function may return a secret *value* in a dict — only the reference string,
   because those dicts get serialised onto the wire and into reports.
9. **Config additions are additive.** A `config.yaml` written before a block
   existed must keep loading and behaving identically. `providers:` and
   `budgets:` both default to empty, and `provider_for()` returns `None` for a
   bare vendor kind so v1 routing is untouched. The example projects are the
   canaries: CI runs all four end to end.

## Where a new capability goes

Put it in `agent_arena/service/`, then let the CLI and the browser API call it.

```
   arena CLI            web/api.py            import agent_arena
        └────────────────────┼────────────────────┘
                             ▼
                    agent_arena/service/
       secrets · settings · providers · projects · runs · export
                             │
   config · runner · metrics · store · connectors · scorers   (core/)
```

The rule that keeps this honest: **nothing may be UI-only.** Before this layer
existed, project creation lived inside `web/api.py`, so the UI could scaffold a
project the CLI could not reach — and neither could delete one. If you add a
verb to the browser without adding it here, you have rebuilt that problem.

Two conventions bind everything in the layer:

- **Every destructive function takes `dry_run: bool = False` and returns the
  same plan dict either way.** One code path, one branch at the end. If the
  plan and the execution can diverge, the confirmation dialog is lying about
  what is going to happen.
- **Caller-supplied names are hostile.** A project name or run id arriving from
  HTTP is untrusted input. `service/paths.py` is the one place that check
  lives — `resolve_within` proves the path is inside the directory you meant
  before anything unlinks it. Do not hand-roll a second version of it.
- **A run that stopped early says so.** Cancellation and budget caps both keep
  the results already collected, because those calls were already paid for. The
  leaderboard carries a note saying how many of the planned calls the numbers
  cover. A truncated sweep presented as a complete one is the quiet lie this
  project exists to avoid.

## Before you push

```bash
pip install -e ".[dev]"
pytest -q                                              # 620 tests, all offline

arena validate --project projects/support_triage
arena evaluate --project projects/support_triage --quiet --no-report
arena evaluate --project projects/pipeline_demo  --quiet --no-report
```

CI runs the suite on Python 3.10–3.13 with no provider SDK installed, plus every
example project end to end.

## The documentation site

`https://adityamhaske.github.io/agent-arena` is built by `site/build.py` and
deployed by `.github/workflows/pages.yml` on every push to `main` that touches
docs or `site/`.

**The site is not a second copy of the docs.** Every page except the landing
page is rendered from a markdown file that already lives in this repo, so a doc
edit ships to the site automatically. Adding a page is one line in
`site/build.py`'s `PAGES` list.

```bash
pip install -r site/requirements.txt
python site/build.py            # → site/_build, links rooted at /
python site/check_links.py      # fails on any broken internal link
```

Rules for the site:

- **Exactly one `<h1>` per page.** The document's own `# Title` is promoted into
  the page shell; do not add another in a template.
- **Containment must not depend on JavaScript.** Wide tables and code blocks are
  contained by CSS alone. `site/assets/site.js` is progressive enhancement only
  (theme toggle, copy buttons, scroll-spy); every page must lay out correctly
  with it blocked.
- **Link rewriting is load-bearing.** Markdown written for GitHub uses
  `../docs/FOO.md`, which 404s on a website. `build.py` rewrites those; the link
  checker fails the build if any internal link resolves to nothing.
- Verify layout at 320px through 2560px before pushing a style change.

## Releasing

Follow this in order. **Steps 2 and 5 are the ones that get forgotten.**

1. **Decide the version.** Semantic versioning against the public surfaces listed
   in `CHANGELOG.md` under *Stability*. A change to the `config.yaml` schema, the
   `Scorer`/`Connector` contracts, or CLI flags is breaking.
2. **Update `CHANGELOG.md`.** Add a section for the version, dated, using the
   Keep a Changelog headings (Added / Changed / Fixed / Removed). **This file is
   the Releases page on the website** — `site/build.py` renders it at
   `/releases/`, so writing the changelog *is* publishing the release notes.
   There is no separate copy to keep in sync, and no step where you edit the
   website by hand.
3. **Bump the version in two places, which must match:**
   - `pyproject.toml` → `version`
   - `agent_arena/__init__.py` → `__version__`
4. **Verify end to end** — the full "Before you push" block above, plus
   `python site/build.py && python site/check_links.py`.
5. **Tag and release.** `git tag -a vX.Y.Z -m "..."` and push the tag, then
   create the GitHub release with the same notes as the changelog section.
6. **Confirm the site updated.** The push to `main` triggers the Docs site
   workflow; check that `/releases/` shows the new version. If the deploy job is
   *skipped* rather than run, GitHub Pages is not enabled — see below.

### If the docs site stops deploying

The workflow tries to enable Pages itself, but the default `GITHUB_TOKEN` is
often refused (`Resource not accessible by integration`). That is a one-time
manual step, not a build failure:

**Settings → Pages → Build and deployment → Source: GitHub Actions.**

Until it is set, the build still compiles every page and runs the link check;
only the deploy job is skipped. The build log line
`Pages configure step outcome:` tells you which state you are in.

## Conventions

- Comments explain *why*, not *what*. The code says what it does.
- Match the surrounding style; this codebase is deliberately plain.
- Tests are named for the behaviour they protect, not the function they call.
- Never skip, disable or quarantine a test to get CI green.
- When a number appears in the README or on the site (test counts, accuracy
  figures, example output), it must come from a real run.
