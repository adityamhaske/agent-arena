# Continuous integration

Three workflows. Each checks something specific and non-obvious.

## `ci.yml`

Runs on every push to `main`, every pull request, and on demand.

### Job: `test`

Matrix over Python **3.10, 3.11, 3.12, 3.13**, `fail-fast: false` so one version
failing still reports the others.

```yaml
- name: Install
  run: pip install -e ".[dev]"
- name: Test
  run: pytest -q
```

**No provider SDK is installed, on purpose.** The workflow says so in a comment:

> The arena's core has no hard third-party dependency and every provider imports
> lazily, so the whole suite must pass with nothing but PyYAML and pytest
> present. If this job ever needs `anthropic` installed to go green, that
> invariant has been broken.

This job exists as much to protect invariant 1 as to run the tests.

### Job: `examples`

The example projects are documentation, so this treats them as such:

```bash
arena validate --project projects/support_triage
arena validate --project projects/doc_extraction
arena validate --project projects/pipeline_demo

arena evaluate --project projects/support_triage --quiet --no-report
arena evaluate --project projects/doc_extraction  --quiet --no-report
arena evaluate --project projects/pipeline_demo   --quiet --no-report
```

Then two checks that catch different classes of bug:

**A scaffolded project must run immediately.**

```bash
arena init /tmp/scaffold --name scaffold_check
arena evaluate --project /tmp/scaffold --quiet --no-report
```

If `arena init` produces something that does not run, the first thing every new
user does fails. This also catches a missing template in the package data.

**End to end over real HTTP against a local model server.**

```bash
python demo/fake_local_server.py --port 11434 &
# wait for readiness
arena validate --project projects/local_demo
arena evaluate --project projects/local_demo --trials 1 --quiet --no-report
```

`demo/fake_local_server.py` speaks the OpenAI-compatible API, so the local-model
path is exercised for real — sockets, HTTP, JSON parsing — with no model
installed. Mocks at the connector layer would not catch a malformed request body.

## `release.yml`

Triggered by a `v*.*.*` tag, or manually for a TestPyPI dry run.

| Job | Does |
|---|---|
| `build` | `python -m build`, uploads `dist/` as an artifact |
| `verify` | Installs the built **wheel** into a clean venv with no repo checkout on the path |
| `publish` | PyPI Trusted Publishing via OIDC — no stored token to leak |

The `verify` job is the point of the workflow. It asserts that the packaged data
actually shipped:

- `arena --version` runs
- `arena scorers` runs, proving the package imports
- `arena init` into a temp dir, then `arena evaluate` on it, proving `templates/`
  rode along in the wheel
- `agent_arena/web/static/index.html` exists in the installed package

Package-data omissions are the classic release bug in this layout: everything
works from a checkout and breaks for anyone who installs from PyPI. That failure
mode is invisible without exactly this check.

Publishing uses `pypa/gh-action-pypi-publish` with `permissions: id-token: write`
and an `environment: pypi`, so there is no long-lived API token anywhere and the
release can be gated in repository settings.

## `pages.yml`

Builds and deploys the documentation site on pushes to `main` that touch docs or
`site/`.

```bash
python site/build.py       # → site/_build
python site/check_links.py # fails the build on any broken internal link
```

The link checker matters because markdown in this repo is written for GitHub —
`../docs/FOO.md` — which 404s on a website. `build.py` rewrites those, and the
checker proves the rewriting worked. It currently checks 760 internal links
across 23 pages.

If the deploy job is *skipped* rather than run, GitHub Pages is not enabled:
**Settings → Pages → Build and deployment → Source: GitHub Actions**. The build
still compiles and link-checks either way.

## Reproducing CI locally

```bash
pip install -e ".[dev]"
python3 -m pytest -q

arena validate --project projects/support_triage
arena evaluate --project projects/support_triage --quiet --no-report
arena evaluate --project projects/doc_extraction  --quiet --no-report
arena evaluate --project projects/pipeline_demo   --quiet --no-report

arena init /tmp/scaffold --name scaffold_check
arena evaluate --project /tmp/scaffold --quiet --no-report

python3 site/build.py && python3 site/check_links.py
```

To reproduce the no-SDK condition exactly, use a fresh virtualenv and install
only `-e ".[dev]"` — an editable install in an environment where you previously
ran `pip install anthropic` will not prove the invariant.
