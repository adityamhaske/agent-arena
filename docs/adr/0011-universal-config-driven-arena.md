# ADR 0011 — A universal, config-driven arena

**Status:** Accepted
**Date:** 2026-08-06
**Supersedes:** nothing. Additive to ADRs 0001–0010.

## Context

The original Agent Arena answers one question: *does splitting a task across
multiple agents lose information at the coordination boundary?* To answer it
cleanly, everything except the architecture is held fixed — one model (Gemini
2.5 Flash), two hardcoded tasks, graders written against a specific SQLite
schema, and a `run_baseline.py` whose `--task` flag is a closed enum.

That rigidity is correct for the experiment and useless for the adjacent
question people actually keep asking: *which model should I use for my
project?* Answering that means varying the model and holding the task fixed —
the exact inverse — and doing it for projects whose notion of "correct" the
harness cannot know in advance.

Three options were considered:

1. **Extend the existing harness.** Add `--model`, generalise the graders,
   parameterise the tasks. Rejected: the existing code's value is that its
   variables are pinned. Making the task, model, scorer and metric all
   configurable turns a controlled experiment into a general framework wearing
   the experiment's clothes, and every future change risks the published
   finding.
2. **A separate repo.** Rejected as premature: the two share a philosophy and
   an audience, and splitting now costs more than it saves.
3. **A separate, additive package in the same repo.** Chosen.

## Decision

Add `agent_arena/`, a config-driven engine containing no project-specific
logic, alongside the untouched `core/` + `evals/` harness. A project is a
folder holding a config file and test cases; the engine reads it at runtime.

Six choices are load-bearing.

### 1. The project folder is the entire contract

No project-specific code in the engine, no hardcoded paths, no registry of
known projects. Adding a project means adding a directory. This is what makes
the same command work for a classifier and a document extractor.

### 2. The core has no hard dependencies, and providers load lazily

Only PyYAML, and even that is optional (JSON works). Every provider SDK is
imported inside the call that needs it. The consequence that mattered during
development: the whole engine and its 170-test suite run in an environment
with no provider SDK and no API key. A harness you cannot test offline is a
harness you cannot trust.

The deterministic `mock:` provider exists for the same reason, and doubles as
a synthetic baseline projects can keep in their model list permanently.

### 3. Hard constraints disqualify; they do not penalise

A model that lacks a required capability or breaches a privacy requirement is
excluded from the ranking with a stated reason, not given a lower score. A
weighted average can always be rescued by strength elsewhere — "unusable" is
not a quantity.

Disqualified models are also excluded from min-max normalisation ranges, so an
unusable outlier cannot distort how the real candidates compare.

### 4. Unknown is not zero

An unmeasurable metric — almost always cost, for a model we have no price for
— has its weight redistributed across that model's measurable metrics, and the
report says so. Scoring it zero would punish a model for a gap in *our*
catalog; treating it as free would flatter it. Neither is a measurement.

The same reasoning drives what the shipped catalog contains: prices we can
source, and nothing else. No invented numbers for providers we cannot verify.

### 5. Privacy facts are declared by the project, not assumed by the engine

Whether a DPA is in place, whether training opt-out applies, whether ZDR is
enabled are properties of the customer's contract and platform, not of the
model. The catalog therefore declares almost no privacy attributes, and a
missing attribute **fails** a privacy gate rather than passing silently — the
safe direction for a compliance requirement. The one exception is a documented
model-level restriction (Claude Fable 5 cannot run under zero data retention),
recorded as an explicit `false`.

### 6. Accuracy excludes failed calls; reliability counts them

Averaging errors into accuracy as zeros conflates "answered wrongly" with
"did not answer", which are different failures with different fixes. They are
measured separately, `reliability` is weightable, and a run with unweighted
errors is flagged in the report.

## Consequences

**Good.** Evaluating a new project is a folder, not a patch. The composite is
auditable — the report shows each metric's raw value, its normalised value and
its weighted contribution. Results accumulate in SQLite, so regressions across
model releases are queryable. `--fail-under` makes the arena a CI gate.

**Costs.** Two evaluation systems live in one repo, which will confuse a first
reader until they hit the table in `docs/UNIVERSAL_ARENA.md`. The composite
score's authority depends entirely on weights a human chose; the report leads
with the trade-off the winner makes rather than the number alone, but the
number will still be quoted out of context. The built-in catalog will drift
from provider price lists and needs a documented refresh.

**Deliberately out of scope for now.** Multi-turn and tool-using evaluations
(a test case is one prompt and one completion); statistical significance
testing beyond flagging small margins; async/streaming execution — the
thread pool is sufficient for API-bound work.
