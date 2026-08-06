"""Project-local scorers.

Every ``.py`` file in this folder is imported at run time and anything it
defines becomes an ``eval_type`` your test cases can name. Delete this file if
the built-in scorers cover you.

Three ways to register, all equivalent:
"""

from agent_arena.scorers import Scorer, ScoreResult, scorer


class WordLimitScorer(Scorer):
    """1) A Scorer subclass with a `name` — the most flexible form."""

    name = "word_limit"
    requires_reference = False
    description = "Passes when the answer stays under params.max_words."

    def score(self, output, reference, context):
        limit = int(context.params.get("max_words", 50))
        words = len(output.split())
        ok = words <= limit
        return ScoreResult(
            score=1.0 if ok else max(0.0, 1.0 - (words - limit) / limit),
            passed=ok,
            reason="" if ok else f"{words} words, limit {limit}",
            # Custom metrics can be weighted in config just like accuracy.
            metrics={"word_count": float(words)},
        )


@scorer("mentions_reference_id", requires_reference=True)
def mentions_reference_id(output, reference, context):
    """2) A decorated function, for one-liners."""
    hit = str(reference).lower() in output.lower()
    return ScoreResult(score=1.0 if hit else 0.0, passed=hit)


# 3) An explicit mapping, if you would rather be literal about it.
SCORERS = {"word_cap": WordLimitScorer}
