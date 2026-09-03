# Contributing to Agent Arena

Thanks for wanting to help. This document is what you need to get a pull request
merged: how to set up, the rules the codebase will not bend on, and the checks
that must be green before you push.

[AGENTS.md](AGENTS.md) holds the same rules as terse working notes, plus the
release process. This file is the friendlier version, not a different one — if
you find them disagreeing, that is a bug worth an issue.

---

## Getting set up

```bash
git clone https://github.com/adityamhaske/agent-arena
cd agent-arena
pip install -e ".[dev]"
python3 -m pytest -q
```

You should see **574 passed** in about 12 seconds. The whole suite runs offline:
no API key, no network, and — deliberately — no provider SDK installed. If it is
not green before you have changed anything, fix that first; you need Python
3.10 or newer and nothing else.

Then run an example project, which is the fastest way to see what the tool
actually does:

```bash
arena evaluate --project projects/support_triage
```

---

## The six invariants

These are not style preferences. Breaking one is a bug, not a trade-off, and a
PR that breaks one will be sent back however good the feature is.

**1. The engine is stdlib-only.** PyYAML is the single runtime dependency, and
even that is optional — JSON config and test files work without it. Every
provider SDK is imported lazily, inside the code path that needs it.

*Why:* `pip install agent-arena` must pull in nothing you did not ask for. An
evaluation harness that drags in half of PyPI cannot be added to somebody else's
production repo, which is where this belongs. The CI test job installs **no**
provider SDK on purpose — if the suite ever needs `anthropic` present to pass,
the invariant is already broken and CI is the thing that tells you. Never add a
dependency to make a test pass; write the test so it does not need one.

(`site/requirements.txt` is build-time only — nothing in it is imported by the
`agent_arena` package. Adding to it is not an exception to this rule, but adding
to `pyproject.toml`'s `dependencies` is.)

**2. The browser UI adds no dependency.** `agent_arena/web/` is `http.server`
plus vanilla JavaScript. No Flask, no npm, no CDN, no build step.

*Why:* `arena ui` has to work on a laptop with no toolchain and no internet. A
build step would also mean shipped artifacts that can drift from their source.

**3. The UI never re-implements the engine.** Rankings come from
`core/metrics.build_leaderboard`; `web/language.py` only re-words them.

*Why:* two ranking implementations means two answers. If the UI and the CLI ever
disagree about who won, the CLI is right and the UI has a bug.

**4. Never fabricate a number.** A model with no sourced price gets **no** cost
metric rather than a guessed one. A sweep that cannot separate two models says
so instead of printing a winner.

*Why:* people spend real money on this output. A guessed price is indistinguishable
from a sourced one once it is in a table, and honesty about resolution is the
product. See [Adding a model price](#adding-a-model-price).

**5. A project is a folder, not code.** `config.yaml` + `tests.yaml`. There is no
second code path and no plugin system to extend.

*Why:* the moment there are two ways to define an evaluation, one of them rots.
If your feature needs a new kind of project, it probably needs a new config key.

**6. The example projects are documentation.** `projects/` runs offline in CI. If
those projects stop validating or running, the docs are lying.

*Why:* every example in the README is a command a reader will paste. CI runs all
of them end to end for exactly that reason.

---

## Adding a scorer

A scorer turns one model output into a number in `[0, 1]`. Most scorers should
**not** go in this repo: project-specific grading lives in the project folder,
where `scorers/` is loaded automatically.

```python
# projects/my_project/scorers/tone.py
from agent_arena.scorers import Scorer, ScoreResult

class ToneScorer(Scorer):
    name = "tone"                       # this is the `eval_type` in your tests

    def score(self, output, reference, context):
        polite = "please" in output.lower()
        return ScoreResult(
            score=1.0 if polite else 0.0,
            passed=polite,
            reason="" if polite else "no please",
            metrics={"politeness": 1.0 if polite else 0.0},
        )
```

Three registration styles are recognised, all equivalent: a `Scorer` subclass
with a `name`, a function decorated with `@scorer("name")`, or a module-level
`SCORERS = {"name": ScorerClass}` mapping. Use whichever reads best.
[`projects/doc_extraction/scorers/currency.py`](projects/doc_extraction/scorers/currency.py)
is a worked example, and its docstring explains why that knowledge belongs in
the project rather than in the engine.

Notes that save review rounds:

- Return a `ScoreResult`. A bare number or bool is tolerated, anything else
  raises `ScorerError`.
- `score` is clamped to `[0, 1]` and `passed` defaults to `score >= 0.5`.
- Extra numbers go in `metrics={...}`; those become project-specific metrics the
  config can weight by name, exactly like `accuracy`.
- Anything beyond the output and the reference comes from `context`
  (`ScoringContext`): `context.params` merges scorer options with the test case's
  own `params`, and `context.judge` is a callable bound to the project's judge
  model.

**A scorer only belongs in `agent_arena/scorers/builtin.py` if it is domain-free**
— useful to a project that has nothing in common with yours. `contains` and
`json_match` qualify; "ISO currency codes" does not. If you are adding one, it
needs tests in `tests/test_scorers.py` and a row in the scorer table in
[`docs/UNIVERSAL_ARENA.md`](docs/UNIVERSAL_ARENA.md).

## Adding a connector

A connector is the uniform model interface: hand it a `GenerationRequest`, get a
`GenerationResult` back. See
[`agent_arena/connectors/base.py`](agent_arena/connectors/base.py).

```python
class MyProviderConnector(Connector):
    provider = "myprovider"

    @property
    def client(self):
        if self._client is None:
            sdk = _require("myprovider", "myprovider")   # lazy: import here, never at module scope
            self._client = sdk.Client(api_key=self.api_key)
        return self._client

    def generate(self, request: GenerationRequest) -> GenerationResult:
        ...     # raise on failure; the runner owns retries
```

The full checklist:

1. Implement `generate`. Raise on failure — the runner handles retries and
   records the error. Populate `input_tokens`/`output_tokens` where the provider
   reports them; fall back to `estimate_tokens` only when it reports nothing.
2. **Import the SDK lazily**, via `_require(module, extra)` so the failure
   message names the exact `pip install` that fixes it. A module-level
   `import anthropic` breaks invariant 1 and CI will catch it.
3. Register it in `CONNECTORS` in
   [`connectors/registry.py`](agent_arena/connectors/registry.py). Add a
   `_PREFIX_RULES` entry if the provider's model ids are recognisable on sight,
   and an `_API_KEY_ENVS` entry if it needs credentials.
4. Add an optional extra in `pyproject.toml` under
   `[project.optional-dependencies]` — never to `dependencies`.
5. Implement `healthcheck()` only if the check is instant and meaningful (a
   local server either accepts a socket or does not). Returning `None` — "no
   opinion" — is better than a check that lies.
6. Test it **without the SDK and without the network**. Provider resolution and
   cost accounting are tested directly (`tests/test_connectors.py`); a transport
   is tested against a real `http.server` on a socket
   (`tests/test_local_connector.py`). No test may make a live API call.

## Adding a model price

[`agent_arena/connectors/model_cards.json`](agent_arena/connectors/model_cards.json)
ships prices, context windows, features and privacy facts. It has one rule, and
it is invariant 4 in practice:

> **Only add a number you can source. If you cannot source it, leave it out.**

A missing card is handled honestly — the model gets no cost metric, its cost
weight is redistributed across its other metrics, and the report says so. A
guessed price is not handled at all, because nothing downstream can tell it apart
from a real one. Scoring an unknown price as zero makes an unpriced model look
free; scoring it as worst punishes a model for a gap in our data. Absent is the
only honest third option.

To add one:

- Add the entry under `models`, keyed by the canonical model id. Narrow ids
  inherit from broader ones, so `claude-haiku-4-5-20251001` picks up
  `claude-haiku-4-5` — add the broad id, not every dated snapshot.
- Prices are USD per **million** tokens: `input_usd_per_mtok`,
  `output_usd_per_mtok`, and the `cache_read_`/`cache_write_` pair where the
  provider charges for caching. Omit a field you cannot source rather than
  writing `0`.
- Update `as_of` at the top of the file to the date you checked, and **put the
  provider's public price page in the PR description.** That link is the review.
- Leave `privacy` empty for real models unless it is a documented *model-level*
  restriction. Whether a DPA is in place or training opt-out applies is a
  property of your contract, not of the model, so it belongs in a project's own
  pricing file.
- Check the result: `arena models --project projects/support_triage`.

Contributors who need numbers we cannot ship — negotiated rates, a provider we
do not cover — do not need this file at all. `pricing.path`, inline
`pricing.models`, and per-model `card:` overrides all layer over the catalog.

---

## Tests

- **Name a test for the behaviour it protects, not the function it calls.**
  `test_unknown_model_id_asks_for_an_explicit_provider`, not `test_infer`.
- **Every test module's docstring says why those tests exist.** Read the top of
  `tests/test_connectors.py` for the shape.
- **Write tests that pass with nothing installed.** `tests/conftest.py` writes
  project fixtures as JSON precisely so the suite does not depend on PyYAML.
- **Never skip, disable or quarantine a test to get CI green.**
- Errors raised by the engine subclass `ArenaError`
  ([`core/errors.py`](agent_arena/core/errors.py)) and the message points at the
  exact fix — the config key to set, the line to change, the command to run. A
  test asserting on that message is a good test.

## Style

The codebase is deliberately plain. Match the file you are editing.

- Comments explain **why**, not what. The code already says what it does.
- Module docstrings explain the module's reason to exist.
- No new abstractions unless the change genuinely needs one.
- When a number appears in the README, in a docstring or on the site (test
  counts, accuracy figures, example output), it must come from a real run.

---

## Before you push

```bash
pip install -e ".[dev]"
python3 -m pytest -q                                   # 574 tests, all offline

arena validate --project projects/support_triage
arena evaluate --project projects/support_triage --quiet --no-report
arena evaluate --project projects/pipeline_demo  --quiet --no-report
```

If you touched anything under `docs/` or `site/`, also:

```bash
pip install -r site/requirements.txt
python site/build.py            # → site/_build
python site/check_links.py      # fails on any broken internal link
```

CI runs the suite on Python 3.10–3.13 with no provider SDK installed, plus every
example project end to end, plus a freshly scaffolded project and a local model
server over real HTTP. Everything above runs on your machine first so you are not
finding that out from a red check.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org), with an optional
scope — this is what the history actually uses:

```
feat(targets): evaluate whole pipelines, not just single model calls
fix(site): repair the deploy gate so the site actually publishes
docs(readme): explain both projects in depth
style(site): modern minimalist design system and off-canvas mobile drawer
refactor(site): refine documentation page shell
chore(git): expand .gitignore to cover caches, editor configs and secrets
```

| Type | Use it for |
|---|---|
| `feat` | New behaviour a user can observe |
| `fix` | A bug fix |
| `docs` | Documentation and the docs site's content |
| `refactor` | Restructuring with no behaviour change |
| `style` | Formatting, whitespace, visual design; no logic |
| `chore` | Tooling, config, housekeeping |
| `release` | A version bump (see the release process in AGENTS.md) |

The subject line says what changed, in the imperative, without a trailing period.
The scope is the area touched (`site`, `ui`, `targets`, `readme`, `local_demo`)
and is optional. PR titles follow the same convention — they become the merge
commit.

## Pull requests

- One concern per PR. A refactor and a feature in the same diff is two reviews
  pretending to be one.
- Say **why** in the description, not just what. The what is in the diff.
- Say how you verified it, and paste the output if it is a number.
- New behaviour comes with a test. A bug fix comes with the test that would have
  caught it.
- If your change affects the `config.yaml` schema, the `Scorer`/`Connector`
  contracts, or CLI flags, it is a **breaking change** under the stability table
  in [`CHANGELOG.md`](CHANGELOG.md) — say so in the PR.
- Not sure whether an idea fits? Open an issue first.
  [`docs/ROADMAP_10X.md`](docs/ROADMAP_10X.md) records both where this is going
  and what it deliberately will not become.

## Also worth knowing

- Contributions are licensed under the repository's [MIT licence](LICENSE).
- Behaviour in issues, PRs and discussions is covered by the
  [Code of Conduct](CODE_OF_CONDUCT.md).
- **Found a security problem? Do not open an issue.**
  [`SECURITY.md`](SECURITY.md) says where to send it and what is in scope.

