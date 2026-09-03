# Non-goals

What Agent Arena deliberately will not become. This page exists so contributors
do not build the wrong thing in good faith, and so users know what to expect.

Each of these looks like an obvious improvement. Each would cost the project the
thing that makes it worth using.

## A hosted SaaS

**Why not.** The moment results leave your machine, the tool inherits a
data-handling problem it does not currently have. Test cases are frequently built
from production traffic and carry real customer data; model outputs carry
whatever the inputs carried. Right now the honest answer to "where does my data
go?" is "nowhere" — that is a feature no amount of hosted convenience replaces.

It would also break the workflow that makes the tool safe to adopt: prove your
scorers and weights against offline `mock:` models before spending anything.
Offline-first stops being the default the moment there is a server.

**If you need shared results:** the SQLite database and the JSON reports are
portable and committable. Point the arena at a shared path.

## More public benchmarks

**Why not.** The project's entire thesis is that someone else's benchmark cannot
answer your question. MMLU tells you how a model does on a task you did not
choose, scored by criteria you did not pick. Shipping an MMLU integration would
contradict the reason to use this tool at all.

**If you want a public benchmark:** use a harness built for it. They are good at
that and this is not trying to be.

## A plugin marketplace

**Why not.** A project folder and a `scorers/*.py` file are already the extension
mechanism, and they are simpler than any registry: no manifest, no versioning, no
compatibility matrix, no distribution channel to secure. A plugin ecosystem also
creates a supply-chain problem the dependency policy exists to avoid.

**If you want to share a scorer:** it is one file. Publish it, or contribute it
as a builtin if it generalises.

## An agent that writes your config

**Why not.** The config *is* the thinking. Deciding that accuracy is worth 55% and
cost 25%, that below 70% accuracy a model is unusable, that 4 seconds at p95 is
too slow — that is the actual work of making the decision, and the tool's value
is in forcing it to be explicit.

Automating it produces evaluations nobody understands well enough to trust, and
an untrusted evaluation does not change anyone's mind, which is the only thing an
evaluation is for.

**What the tool does instead:** the wizard *asks the questions* in plain
language, then writes the YAML. That is a different thing — it elicits the
decision rather than guessing it.

## Dropping the stdlib-only rule

**Why not.** It is why `pip install agent-arena` is instant, why the tool works
on a locked-down laptop behind an artifact proxy, why the supply-chain surface is
near zero for a tool that holds API keys, and why a security reviewer can read
the whole thing.

Every feature on the roadmap is achievable without breaking it — including the
multi-page UI, which is scoped as an **optional** `[ui]` extra with a pre-built
bundle so the default install stays clean and CI keeps proving it.

See [../security/dependency-policy.md](../security/dependency-policy.md) for the
bar a new dependency must clear. It is high, not infinite.

## Becoming an agent framework

**Why not.** The arena measures systems; it does not build them. A `run:` target
puts *your* pipeline on the leaderboard without the arena knowing anything about
how it works, and that ignorance is the point — it is what lets the arena compare
a LangGraph pipeline, a hand-rolled loop and a single model call on equal terms.

Adding orchestration primitives would make the arena a competitor to the thing it
is supposed to measure, and a benchmark with a stake in the outcome is not a
benchmark.

## Merging the two systems in this repository

The multi-agent handoff study under `studies/` shares **zero imports** with the
arena, deliberately. The study is complete and frozen, kept for reproducibility;
its value is that the committed traces and the code that produced them have not
moved. Refactoring them to share utilities would put a frozen artefact back in
motion for no benefit.

## What this means for a contribution

If your idea is on this page, it will be declined — not because it is a bad idea,
but because it is a different product. Two things help:

- Say which non-goal you think should change, and why the reasoning above is
  wrong. These are judgements, not commandments, and a good argument beats a
  precedent.
- Check whether the thing you want is already reachable through an existing
  extension point: a custom scorer, a `run:` target, a hook, or a pricing
  override. Most requests are.

See [../../CONTRIBUTING.md](../../CONTRIBUTING.md).
