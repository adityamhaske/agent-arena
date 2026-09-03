# The plain-language layer

`agent_arena/web/language.py` — 564 lines whose entire job is re-wording. It is
the reason a non-technical stakeholder can read a result, and it is the piece of
this project most easily mistaken for decoration.

## What it does not do

It does not compute anything. Rankings come from
`core/metrics.build_leaderboard`; this module receives the finished leaderboard
and describes it. That separation is invariant 3, and it is what guarantees the
UI and the CLI can never disagree about who won.

## The conversions

| Function | Turns | Into |
|---|---|---|
| `out_of_100` | `0.833` | "83 out of 100" |
| `money` | `0.00006` | "6¢ per 1,000 uses" |
| `duration` | `190.0` | "190 milliseconds" |
| `speed_word` | `190.0` | "instant" |
| `ratio_phrase` | two numbers | "4.9× cheaper" |
| `metric_question` | `"cost"` | the question that metric answers |
| `explain_weights` | a weights dict | a sentence about what you are optimising for |
| `explain_constraints` | a constraints dict | plain statements of your non-negotiables |

`out_of_100` is a small decision with a large effect. "83.3% accuracy" invites
false precision; "gets 83 out of 100 right" is the same number in a form people
reason about correctly — and it makes the comparison sentence natural: *"about 14
more answers right in every 100."*

## The composed outputs

| Function | Produces |
|---|---|
| `summarise_entry` | One model's line: what it gets right, what it costs, how fast |
| `explain_verdict` | The whole recommendation, including the trade-off against the runner-up |
| `explain_disqualification` | Why a model was ruled out **and** whether to fix the model or the requirement |
| `plain_notes` | Resolution warnings — "these two are too close to call" |
| `plain_error` | An exception rendered as something actionable |

## `preset_for_eval_type`

The wizard asks *what job is the AI doing?* in plain language — "sort things into
categories", "pull specific details out of text" — and this maps the answer to a
scorer, a starting prompt and initial weights.

It is the inverse of the config file: instead of requiring the user to know that
their job is a `classification` task with a `labels` option, it asks what they
are doing and writes the YAML a developer would have written.

## Rules for adding copy

1. **Never state a number the engine did not produce.** Invariant 4 applies to
   prose. If a comparison cannot be computed, omit the sentence rather than
   hedging it.
2. **Handle `None` everywhere.** Every formatter returns "—" for a missing value.
   An unpriced model has no cost; a skipped model has no accuracy. Copy that
   assumes a number exists will render "None" in front of a stakeholder.
3. **Keep the reasoning visible.** "It is 4.9× cheaper and 7.9× faster" earns the
   recommendation. "Use Small/fast" alone asks for trust the tool has not yet
   earned.
4. **Test the sentence, not the function.** `tests/test_web.py` asserts on the
   rendered wording, because a wrong sentence in front of someone who cannot
   check it is worse than a wrong number in front of someone who can.
