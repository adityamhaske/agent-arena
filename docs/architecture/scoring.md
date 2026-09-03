# Scoring

`agent_arena/scorers/` — turning one model output into a number in [0, 1].

## The contract

```python
class Scorer(ABC):
    name: str
    @abstractmethod
    def score(self, output: str, reference: Any, context: ScoringContext) -> ScoreResult: ...
```

`ScoreResult` carries:

| Field | Meaning |
|---|---|
| `score` | 0–1, drives the accuracy metric |
| `passed` | Boolean verdict; may be `None` for unscored types |
| `reason` | Why it scored that way — shown in reports and drill-downs |
| `detail` | Scorer-specific structured data |
| `metrics` | Extra numbers, weightable in `metrics.weights` by name |

That last field is the extension point most people miss. A scorer that returns
`metrics={"citation_rate": 0.8}` makes `citation_rate` a first-class leaderboard
dimension with no engine change.

`ScoringContext` provides the test case, the model key, the options block from
`scorers.options.<type>`, the project root, and `judge` — a callable for scorers
that need a model of their own.

## The ten builtin eval types

Run `arena scorers` to list them.

| Type | What it does |
|---|---|
| `classification` | Finds which of `labels` the output selects, then compares to the reference |
| `exact_match` | Normalised string equality — case, punctuation and whitespace insensitive by default |
| `contains` | Substring containment; a list reference requires all or any depending on `mode` |
| `regex` | Regex search over the output, with optional capture-group comparison |
| `numeric` | Extracts a number and compares with absolute or relative tolerance |
| `json_match` | JSON-parses the output and scores the fraction of reference keys that match |
| `semantic` | Token-set cosine similarity, or your own embedding function |
| `code_exec` | Executes generated code plus reference assertions in a subprocess |
| `llm_judge` | Grades with a judge model and returns its 0–1 score |
| `manual` | Always 0.5, unscored — collects outputs for human grading |

Two carry warnings. `code_exec` runs generated code in a subprocess; it is
**isolation, not a sandbox** — see
[../security/hardening.md](../security/hardening.md). `llm_judge` makes your
evaluation depend on another model's judgement, which needs its own validation
before you trust a ranking built on it.

Per-type options live in `scorers.options`:

```yaml
scorers:
  default: classification
  options:
    classification:
      labels: [billing, technical, account, other]
    numeric:
      tolerance: 0.01
```

## Custom scorers

Drop a file in the project's `scorers/` folder. It is discovered automatically —
no registration, no plugin manifest.

```python
# projects/my_project/scorers/tone.py
from agent_arena.scorers import Scorer, ScoreResult

class ToneScorer(Scorer):
    name = "tone"

    def score(self, output, reference, context):
        polite = "please" in output.lower()
        return ScoreResult(score=1.0 if polite else 0.0, passed=polite)
```

Then `eval_type: tone` on a case, or `scorers.default: tone`.

`projects/doc_extraction/scorers/currency.py` is a committed worked example.

## Hooks

`hooks.py` in the project folder touches data on the way through:

| Hook | When | Use for |
|---|---|---|
| `pre_request` | Before the model is called | Rewriting the prompt, injecting context |
| `post_process` | After the output, before grading | Stripping markdown fences, extracting a field, normalising a format |

`post_process` can also override the verdict entirely, which is the escape hatch
for grading that does not fit the scorer shape at all.

Use a hook for shaping and a scorer for judging. Putting judgement in a hook
works but hides it from the reports, because a hook's reasoning does not reach
`ScoreResult.reason`.
