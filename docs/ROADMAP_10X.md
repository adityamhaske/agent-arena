# Taking Agent Arena 10× further

A plan, written against what the code actually is today rather than against a
wishlist. Each lever names the gap, what to build, and roughly what it costs.

The honest starting point: **the engine is good and its reach is tiny.** The
scoring, the constraints, the disqualification logic, the "too close to call"
note — that machinery is sound and there are 258 tests holding it in place. What
limits the project is not the quality of its answers. It is who can ask it a
question, what it is allowed to be asked about, and whether anyone asks twice.

So the multipliers below are almost all about reach and repetition, not about
making the ranking cleverer.

---

## 1. Anyone can use it — not just people who write YAML  ✅ shipped

**The gap.** Every decision the arena helps with — which model, at what cost,
with what accuracy floor — is made by people who mostly do not live in a
terminal. Product leads, ops managers, the person who owns the support queue.
Until this change, using the tool required `pip install`, a hand-written
`config.yaml`, and reading a composite score.

**What shipped.** `arena ui` — a local web app, stdlib-only, no new dependency:

- a five-step wizard that asks *what job is the AI doing?* in plain language and
  writes the same `config.yaml` a developer would have hand-written;
- results as sentences, not scores: *"Use Small/fast. It gets 83 out of 100
  right, costs 6¢ per 1,000 uses, replies instantly. It is not the most accurate
  — Frontier gets about 14 more right in every 100 — but it is 4.9× cheaper and
  7.9× faster."*;
- disqualifications with the reason **and the remedy**;
- **what-if sliders** that re-rank from stored answers with zero new API calls —
  the one thing the UI can do that the CLI genuinely cannot.

**Why this first.** It is the only change here that multiplies the audience
rather than the capability, and the engine was already good enough to deserve it.

**Cost.** Done. ~2,600 lines including tests, no new dependencies.

---

## 2. Evaluate *systems*, not just models

**The gap.** The arena's unit of comparison is one prompt → one completion.
Almost nobody ships that any more. They ship a pipeline: retrieve, plan, call
tools, critique, synthesise. Today you *can* evaluate one — register a connector
that wraps your pipeline — but that path is undocumented, relies on a
`scorers/*.py` import side-effect, and is not what `config.yaml` looks like.

**What to build.** Make "the thing under test" a first-class config field:

```yaml
targets:
  - key: rag_v1
    run: pipelines/rag.py:answer      # any callable: (prompt, **ctx) -> str | dict
  - key: rag_v2_with_critic
    run: pipelines/rag.py:answer
    params: {critic: true}
  - key: baseline_single_call
    model: claude-sonnet-5            # a plain model is just a target too
```

The runner already has the right shape for this — `Connector.generate` is the
seam, and `CallResult` already carries per-call cost and latency. The work is a
`CallableConnector`, letting a target declare its own token/cost accounting, and
teaching `arena models` to describe a target that has no model card.

**Why it is the biggest capability jump.** It changes the question from *"which
model?"* to *"which design?"* — and design decisions are worth far more than
model decisions. It is also the bridge to the multi-agent study sitting in this
same repo: that study's whole finding is that architecture choices produce
failures no model swap can fix, and the arena currently cannot measure them.

**Cost.** Medium. ~500 lines in `connectors/` and `core/config.py`, plus docs.
No change to scoring, metrics or the store.

---

## 3. Turn "probably" into a number you can defend

**The gap.** The arena is already more honest than most harnesses — it refuses
to crown a winner inside 0.02 and says to run more trials. But it cannot say
*how many* more, and it reports no interval at all. A leaderboard with three
models inside two points is presented with the same visual confidence as one
with a runaway winner.

**What to build.** Every call is already in SQLite, so the data is sitting there:

- **Bootstrap confidence intervals** on accuracy and on the composite, resampling
  over test cases (not trials — cases are the unit of generalisation).
- **A power calculation**: "at this variance, separating your top two at 95%
  confidence needs about 40 more cases." Actionable, unlike "run more trials".
- **Per-case significance**: which specific cases actually discriminate between
  the leaders. Those are the ones worth curating; the rest are ballast.
- **Paired comparison**, since every model sees identical cases — a paired test
  is far more sensitive than comparing two independent means, and the arena's
  design already guarantees the pairing.

Render it as an error bar in the UI and one sentence: *"On this evidence these
two are indistinguishable."*

**Why.** This is what converts an evaluation into a decision someone will sign
off on. It also protects the project's core claim to honesty: a 12-case sweep
that implies precision it does not have is the exact failure mode the README
already criticises in other benchmarks.

**Cost.** Medium. ~400 lines in `core/metrics.py`, stdlib `statistics` and
`random` only. Fully offline-testable with mock models.

---

## 4. Make it continuous — a model choice decays

**The gap.** The arena is a one-shot tool used at a decision point. But the
decision rots: providers silently update models, your prompt drifts, your
traffic shifts, prices change. `store.model_history()` and the regression
tracking in `arena history` already exist and are barely surfaced.

**What to build.**

- **`arena watch`** — a scheduled re-run that writes to the same database and
  alerts when a model moves outside its historical band. The comparison logic
  already exists; this is delivery.
- **A GitHub Action** that runs the arena on PRs touching prompts or pipeline
  code, and comments the leaderboard delta. Gate merges with the existing
  `--fail-under`.
- **Provider-change detection**: pin the model card's `as_of`, and flag when a
  model id resolves to different behaviour than the last run recorded.
- In the UI, lead with the trend rather than the last run: *"Haiku dropped 6
  points on your cases three weeks ago."*

**Why.** It converts a tool you use once into infrastructure you keep. That is
the difference between a repo people star and one they depend on.

**Cost.** Small–medium. Mostly a CLI command, a workflow file, and UI wiring
over queries the store already answers.

---

## 5. Get the test cases from reality, not from imagination

**The gap.** Every evaluation is only as good as its cases, and hand-written
cases are the weakest part of every eval anyone builds. People write the easy
ones, miss the ambiguous ones, and get a confident recommendation off a test set
that does not resemble production.

**What to build.**

- **Import** from CSV, JSONL, or a query against the user's own logs — the UI
  wizard already accepts a bulk paste; this is the real version.
- **Coverage analysis**: cluster cases by embedding or by tag, and show what is
  over- and under-represented against real traffic.
- **Disagreement mining**: the highest-information case is one where the leading
  models split. The arena already stores every model's answer to every case, so
  it can point at exactly those and say *"label these five and your ranking gets
  much sharper."*
- **Failure harvesting**: a one-line hook so production failures land in the test
  file, making the eval strictly better every time something goes wrong.

**Why.** It attacks the input side, which is where evaluation quality is
actually decided. Everything else in this list refines how well the arena
answers; this improves what it is being asked.

**Cost.** Small for import and disagreement mining (the data is in the store).
Larger for clustering, which is the first feature that would want an optional
embedding dependency — keep it optional, consistent with the lazy-import rule.

---

## Sequencing

```
now ──▶ 1. UI                    ✅ shipped — widens who can ask
        2. Pipeline targets        widens what can be asked about
        3. Confidence intervals    makes the answer defensible
        4. Continuous runs         makes the answer stay true
        5. Cases from production   makes the question worth asking
```

2 and 3 are independent and can run in parallel. 4 depends on nothing. 5 gets
much more valuable after 2, because a pipeline target produces far richer
per-case output to mine.

## What I would deliberately *not* build

Worth stating, because these are the obvious-looking moves that would cost the
project its character:

- **A hosted SaaS.** The moment results leave the user's machine, the tool
  inherits a data-handling problem it does not currently have, and the offline
  "prove your scorers before you spend" workflow stops being the default.
- **More public benchmarks.** The project's entire thesis is that someone else's
  benchmark cannot answer your question. Shipping MMLU integration would
  contradict the reason to use it.
- **A plugin marketplace.** A project folder and a `scorers/*.py` file are
  already the extension mechanism, and they are simpler than any registry.
- **An agent that writes your config for you.** The config *is* the thinking.
  Automating it produces evaluations nobody understands well enough to trust —
  the wizard asks the questions instead, which is a different thing.
- **Dropping the stdlib-only rule.** It is why `pip install agent-arena` is
  instant and why the UI works on a locked-down laptop. Every feature above is
  achievable without breaking it.
