# UX principles

Five principles, each with the code that implements it. These are not
aspirations — they describe the shipped UI.

## 1. Answer in sentences, not scores

A composite of `0.853` is meaningless to someone deciding whether to change a
production model. `web/language.py` renders the same leaderboard as prose:

> **Use Small/fast (simulated).**
> It gets 83 out of 100 right, costs 6¢ per 1,000 uses, and replies in 190
> milliseconds (instant).
> *Small/fast is not the most accurate — Frontier-class gets about 14 more
> answers right in every 100 — but it is 4.9× cheaper and 7.9× faster.*

Note what the comparison sentence does: it states the trade-off explicitly rather
than letting the reader infer it from a table. The winner being *less accurate*
is the single most important thing about this result, and prose can say so where
a sorted table cannot.

See [plain-language.md](plain-language.md).

## 2. A disqualification always carries its remedy

Being told a model is unusable is half an answer. `explain_disqualification`
returns both the reason and what to do:

> **Cannot use: Tiny (simulated).** It only gets 50 out of 100 right, which is
> below the floor you set.

...paired with whether the fix is a better model or a more realistic
requirement. A user who set `min_accuracy: 0.95` on a hard task needs to hear the
second option, and nothing else in the interface will tell them.

## 3. What-if costs nothing

The sliders re-rank from **already-collected answers**. Changing how much you
care about accuracy versus cost recalculates the leaderboard with no new API
calls and no new spend.

This is the one thing the UI does that the CLI genuinely cannot, and it maps onto
how the decision is actually made: nobody knows their weights up front. They
discover them by watching the ranking move.

It works because `build_leaderboard` takes results as an argument, so the same
function serves a live run and a stored one — which is also why a what-if and a
fresh run can never disagree.

## 4. Never show a traceback

`plain_error` maps raw exception text to a sentence a non-engineer can act on. A
stack trace tells a developer where to look and tells everyone else that the tool
is broken.

The rule for new copy: an error says **what went wrong** and **what to do next**.
No apology, no vagueness, no internal identifiers.

## 5. Progress must be legible while money is being spent

A run against a paid API is a spending event. The job feed shows completed versus
planned, elapsed time, an ETA once there is enough data to estimate one, and a
live feed of what the models are actually saying — capped at the last 40 results.

That last part is deliberate: a progress bar tells you something is happening; a
feed of real outputs tells you whether it is happening *correctly*, early enough
to stop it.

Cancellation is where this is currently incomplete. The API has
`ArenaAPI.cancel_run` and a cancel event on the job, but the runner has no
cooperative check, so a running sweep cannot yet actually be stopped. This is the
most user-visible gap in the shipped product.

## Writing new copy

- Name things the way a reader recognises them, not the way the system is built.
  A person manages *evaluations*, not `ProjectConfig` instances.
- A control says exactly what happens. "Delete project", then a toast that says
  "Deleted".
- Specific beats clever. "Costs 6¢ per 1,000 uses" beats "highly economical".
- Never round away the thing that matters. If two models are indistinguishable on
  the evidence, say that instead of showing a third decimal place.
