# Scorer reference

Ten builtin eval types. `arena scorers` lists them.

Options go under `scorers.options.<type>`; a case picks a type with `eval_type:`
or inherits `scorers.default`.

## `classification`

Finds which of `labels` the output selects, then compares to the reference.

```yaml
scorers:
  default: classification
  options:
    classification:
      labels: [billing, technical, account, other]
```

Reference: the correct label. Tolerant of a model that answers "The category is
billing." rather than "billing" — it looks for a label in the output.

**Fails when** two labels are substrings of each other (`account` and
`account_closure`), or when the model names a label while rejecting it
("this is not billing"). Keep labels short and mutually exclusive.

## `exact_match`

Normalised string equality — case, punctuation and whitespace insensitive by
default.

Reference: the exact expected string. Use for deterministic short outputs.
**Fails when** the model adds a preamble; use `contains` or a `post_process` hook
to strip it.

## `contains`

Substring containment. A list reference requires all or any depending on `mode`.

```yaml
options:
  contains:
    mode: all      # or: any
```

Use for "the answer must mention X and Y". **Fails when** the substring appears
inside a negation — it cannot tell "includes a refund" from "does not include a
refund".

## `regex`

Regex search over the output, with optional capture-group comparison.

Use for structured formats: an order id, a date, a code. **Fails when** the
pattern is anchored too tightly; models vary their surrounding text far more than
the value you want.

## `numeric`

Extracts a number and compares with absolute or relative tolerance.

```yaml
options:
  numeric:
    tolerance: 0.01
    relative: true
```

**Fails when** the output contains several numbers and the wanted one is not
first. Narrow it with a `post_process` hook or use `regex` with a capture group.

## `json_match`

JSON-parses the output and scores the fraction of reference keys that match.

Reference: the expected object. Partial credit is the point — an extraction that
gets four of five fields right scores 0.8, which is far more useful for comparing
models than a pass/fail.

**Fails when** the model wraps JSON in a markdown fence. Strip it in
`post_process`; `projects/doc_extraction` does exactly this.

## `semantic`

Token-set cosine similarity, or your own embedding function.

For free-text answers where wording varies but meaning should not. **Weak by
default** — the builtin is lexical, so it rewards shared vocabulary rather than
shared meaning. Supply an embedding function, or use `llm_judge`, when that
distinction matters.

## `code_exec`

Executes generated code plus reference assertions in a subprocess.

Reference: assertions to run against the generated code.

**This is process isolation, not a sandbox.** The subprocess runs as you, with
your filesystem and your network. Use it on code from a model you control, on
inputs you wrote. See [../security/hardening.md](../security/hardening.md).

## `llm_judge`

Grades with a judge model and returns its 0–1 score.

```yaml
judge:
  model: claude-sonnet-5
  prompt: |
    Score 0-1 how well the answer addresses the question...
```

For qualitative criteria — tone, helpfulness, whether an explanation is correct —
that no deterministic scorer can express.

Three costs, all real: it makes every evaluation call a second model, it costs
money per case, and it makes your ranking depend on another model's judgement.
Validate the judge against human labels on a sample before trusting a leaderboard
built on it.

## `manual`

Always returns 0.5, unscored. Collects outputs for human grading.

Use to run a sweep, export the results, grade by hand, and turn the graded set
into references for a real scorer. That progression — manual first, automated
once you know what "good" looks like — is usually the right order.

## Choosing

| Your output is | Use |
|---|---|
| One of a fixed set | `classification` |
| An exact short string | `exact_match` |
| Free text that must mention things | `contains` |
| A structured value in prose | `regex` or `numeric` |
| A JSON object | `json_match` |
| Free text where wording varies | `semantic`, or `llm_judge` |
| Code | `code_exec` |
| Qualitative | `llm_judge` |
| Not yet known | `manual`, then decide |

## Writing your own

```python
# projects/my_project/scorers/tone.py
from agent_arena.scorers import Scorer, ScoreResult

class ToneScorer(Scorer):
    name = "tone"

    def score(self, output, reference, context):
        polite = "please" in output.lower()
        return ScoreResult(
            score=1.0 if polite else 0.0,
            passed=polite,
            reason="found 'please'" if polite else "no politeness marker",
            metrics={"politeness": 1.0 if polite else 0.0},
        )
```

Discovered automatically from the project's `scorers/` folder. `metrics` entries
become weightable leaderboard dimensions by name.

`projects/doc_extraction/scorers/currency.py` is a committed worked example.
