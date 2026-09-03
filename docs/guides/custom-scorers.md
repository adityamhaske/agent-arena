# Custom scorers

When none of the ten builtins can express what "correct" means for your task,
write one. It is a file in your project's `scorers/` folder — no registration, no
plugin manifest.

## The shape

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
        )
```

Then use it:

```yaml
scorers:
  default: tone
```

or per case:

```yaml
tests:
  - id: refund_request
    input: "..."
    reference: "..."
    eval_type: tone
```

## `ScoreResult`

| Field | Purpose |
|---|---|
| `score` | 0–1. Drives the accuracy metric |
| `passed` | Boolean verdict. `None` for unscored types |
| `reason` | Why. Shown in reports and drill-downs — write it for a human |
| `detail` | Structured data for the drill-down |
| `metrics` | Extra numbers, weightable in `metrics.weights` by name |

`reason` earns its keep the first time you look at a failing case and want to
know why it failed rather than that it did.

## Emitting custom metrics

This is the feature most people miss. A scorer can return numbers that become
first-class leaderboard dimensions:

```python
return ScoreResult(
    score=accuracy,
    passed=accuracy >= 0.8,
    metrics={"citation_rate": cited / total, "hallucinated_refs": bad},
)
```

```yaml
metrics:
  weights:
    accuracy: 0.5
    citation_rate: 0.3
    cost: 0.2
```

No engine change. The composite now includes a dimension only your domain has.

## `ScoringContext`

| Field | Is |
|---|---|
| `test_case` | The whole case — id, input, reference, tags, weight |
| `model_key` | Which model produced this output |
| `options` | The `scorers.options.<name>` block for your scorer |
| `judge` | A callable for grading with a model, if you need one |
| `project_root` | For loading fixtures next to your scorer |

Options make a scorer reusable:

```python
class ThresholdScorer(Scorer):
    name = "threshold"

    def score(self, output, reference, context):
        floor = context.options.get("floor", 0.5)
        ...
```

```yaml
scorers:
  options:
    threshold:
      floor: 0.8
```

## A worked example

`projects/doc_extraction/scorers/currency.py` is committed and real. It grades
extracted currency amounts, where `exact_match` fails on `$1,200.00` versus
`1200` versus `USD 1200` — all the same answer.

That is the shape of the problem custom scorers solve: **domain-specific
equivalence** the generic scorers cannot know about.

## Hooks versus scorers

`hooks.py` in the project folder touches data in flight:

```python
# projects/my_project/hooks.py
def post_process(output, case, context):
    # Strip a markdown fence before json_match sees it.
    text = output.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return text
```

| Use a hook to | Use a scorer to |
|---|---|
| Reshape the output before grading | Decide whether it is correct |
| Strip fences, extract a field, normalise a format | Apply domain-specific equivalence |
| Inject context into the prompt (`pre_request`) | Emit custom metrics |

A hook *can* override the verdict entirely, but doing judgement there hides your
reasoning from the reports — a hook's logic never reaches `ScoreResult.reason`.

## Testing your scorer

Test it directly. It is a plain class.

```python
from projects.my_project.scorers.tone import ToneScorer

def test_a_polite_refusal_still_scores_as_polite():
    result = ToneScorer().score("I'm sorry, please try again.", None, ctx)
    assert result.passed
```

Then run against `mock:` models to confirm it behaves in a real sweep, offline
and free:

```bash
arena evaluate --project projects/my_project --models sim_small
```

Prove the scorer before you spend anything on real models. That is what the mock
connector is for.
