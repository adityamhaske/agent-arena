"""Turning "probably" into a number you can defend.

The leaderboard already refuses to crown a winner inside the noise floor, which
is more honest than most harnesses manage. But it cannot say *how much* more
evidence would settle the question, and it reports no interval at all — so three
models within two points are presented with the same visual confidence as a
runaway result.

Everything here resamples over **test cases**, not trials. A case is the unit of
generalisation: you want to know whether the ranking holds on *other tasks like
these*, not whether it holds if you asked these same twelve questions again.
Resampling trials would answer the second question and quietly report it as the
first.

Stdlib only — ``random`` and ``statistics``. Fully offline, and every function
takes an explicit ``seed`` so a report is reproducible.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

#: Enough resamples for a stable 95% interval without making a report slow.
DEFAULT_RESAMPLES = 2000

#: The conventional level. Exposed so a caller can widen it rather than
#: hard-coding a second number somewhere else.
DEFAULT_CONFIDENCE = 0.95


@dataclass
class Interval:
    """A point estimate and the range the evidence actually supports."""

    point: float
    low: float
    high: float
    confidence: float = DEFAULT_CONFIDENCE

    @property
    def width(self) -> float:
        return self.high - self.low

    def to_dict(self) -> dict[str, float]:
        return {
            "point": round(self.point, 6),
            "low": round(self.low, 6),
            "high": round(self.high, 6),
            "confidence": self.confidence,
        }


@dataclass
class Comparison:
    """Whether two models are actually distinguishable on this evidence."""

    a: str
    b: str
    difference: Interval
    wins: int
    losses: int
    ties: int
    separated: bool
    #: Cases needed *in total* to separate them at this confidence, or None
    #: when they are already separated or the effect is too small to chase.
    cases_needed: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "a": self.a,
            "b": self.b,
            "difference": self.difference.to_dict(),
            "wins": self.wins,
            "losses": self.losses,
            "ties": self.ties,
            "separated": self.separated,
            "cases_needed": self.cases_needed,
        }

    @property
    def sentence(self) -> str:
        """One sentence a reader can act on.

        It always names *accuracy*, because the leaderboard ranks on the
        composite — which also weighs cost and latency. "These two are
        indistinguishable" without that word reads as "the ranking is
        meaningless", when the real meaning is usually the opposite: the
        models answer about equally well, so the ranking is being decided by
        price and speed, which are measured far more precisely.
        """
        if self.separated:
            better, worse = (self.a, self.b) if self.difference.point > 0 else (self.b, self.a)
            gap = abs(self.difference.point) * 100
            return (
                f"{better} is more accurate than {worse} by about {gap:.0f} "
                f"answers per 100 cases "
                f"({int(self.difference.confidence * 100)}% confidence)."
            )
        if self.cases_needed:
            return (
                f"{self.a} and {self.b} are too close to call on accuracy — "
                f"about {self.cases_needed} cases in total would separate them. "
                "Any gap between them here is coming from cost and speed."
            )
        return (
            f"{self.a} and {self.b} are too close to call on accuracy, and the "
            "difference is small enough that more cases may never separate them. "
            "Any gap between them here is coming from cost and speed."
        )


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = fraction * (len(ordered) - 1)
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    weight = index - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def per_case_scores(results: Iterable[Any]) -> dict[str, float]:
    """Mean score per test case, collapsing trials.

    Trials measure consistency on one case; they are not extra evidence about
    the task, so they are averaged rather than treated as independent samples.
    Counting them as samples would shrink every interval by a factor the data
    does not support.
    """
    buckets: dict[str, list[float]] = {}
    for result in results:
        if getattr(result, "status", "ok") != "ok":
            continue
        score = getattr(result, "score", None)
        if score is None:
            continue
        buckets.setdefault(result.test_id, []).append(float(score))
    return {case: statistics.fmean(scores) for case, scores in buckets.items()}


def bootstrap_interval(
    scores: Sequence[float],
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    seed: int = 0,
) -> Interval | None:
    """A percentile bootstrap interval for the mean of ``scores``.

    ``None`` below three cases: an interval computed from one or two points is
    arithmetic, not evidence, and printing it would imply a precision that does
    not exist.
    """
    values = [float(s) for s in scores]
    if len(values) < 3:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(resamples):
        means.append(statistics.fmean(rng.choices(values, k=n)))
    tail = (1.0 - confidence) / 2.0
    return Interval(
        point=statistics.fmean(values),
        low=_percentile(means, tail),
        high=_percentile(means, 1.0 - tail),
        confidence=confidence,
    )


def paired_comparison(
    a_scores: dict[str, float],
    b_scores: dict[str, float],
    a_name: str = "a",
    b_name: str = "b",
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    seed: int = 0,
) -> Comparison | None:
    """Compare two models on the cases they both answered.

    Paired, because the arena's design guarantees every model sees identical
    cases. A paired test cancels out per-case difficulty — the largest source
    of variance in a small eval — and is far more sensitive than comparing two
    independent means, which is what an unpaired test would throw away.
    """
    shared = sorted(set(a_scores) & set(b_scores))
    if len(shared) < 3:
        return None

    deltas = [a_scores[case] - b_scores[case] for case in shared]
    rng = random.Random(seed)
    n = len(deltas)
    means = [statistics.fmean(rng.choices(deltas, k=n)) for _ in range(resamples)]
    tail = (1.0 - confidence) / 2.0
    interval = Interval(
        point=statistics.fmean(deltas),
        low=_percentile(means, tail),
        high=_percentile(means, 1.0 - tail),
        confidence=confidence,
    )
    # Separated when the interval excludes zero: the sign of the difference is
    # consistent across resamples.
    separated = interval.low > 0 or interval.high < 0
    return Comparison(
        a=a_name,
        b=b_name,
        difference=interval,
        wins=sum(1 for d in deltas if d > 0),
        losses=sum(1 for d in deltas if d < 0),
        ties=sum(1 for d in deltas if d == 0),
        separated=separated,
        cases_needed=None if separated else cases_to_separate(deltas, confidence),
    )


def cases_to_separate(
    deltas: Sequence[float], confidence: float = DEFAULT_CONFIDENCE
) -> int | None:
    """Roughly how many cases in total would separate two models.

    A normal-approximation power calculation on the paired differences:
    ``n >= (z * sd / effect) ** 2``. Deliberately approximate — the value of
    this number is that it is *actionable* ("label forty more") rather than
    exact, and the honest alternative is the "run more trials" advice it
    replaces, which does not help at all.

    ``None`` when the observed effect is so close to zero that no realistic
    number of cases would settle it. Telling someone to collect 40,000 cases is
    not advice.
    """
    if len(deltas) < 3:
        return None
    effect = abs(statistics.fmean(deltas))
    if effect <= 1e-9:
        return None
    spread = statistics.pstdev(deltas)
    if spread == 0:
        return len(deltas)
    z = 1.959963985 if confidence >= 0.95 else 1.644853627
    needed = int((z * spread / effect) ** 2) + 1
    if needed > 100 * len(deltas) or needed > 10_000:
        return None
    return max(needed, len(deltas) + 1)


def discriminating_cases(
    a_scores: dict[str, float], b_scores: dict[str, float], limit: int = 10
) -> list[dict[str, Any]]:
    """The cases where two models most disagree.

    These carry all the information about which model is better; a case both
    get right is ballast. Curating these is the cheapest way to sharpen a
    ranking, and the store already holds every model's answer to every case.
    """
    shared = set(a_scores) & set(b_scores)
    scored = [
        {
            "test_id": case,
            "a": a_scores[case],
            "b": b_scores[case],
            "delta": a_scores[case] - b_scores[case],
        }
        for case in shared
        if a_scores[case] != b_scores[case]
    ]
    scored.sort(key=lambda row: abs(row["delta"]), reverse=True)
    return scored[:limit]


@dataclass
class Analysis:
    """Everything the statistics layer can say about one run."""

    intervals: dict[str, Interval] = field(default_factory=dict)
    comparison: Comparison | None = None
    discriminating: list[dict[str, Any]] = field(default_factory=list)
    n_cases: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_cases": self.n_cases,
            "intervals": {key: value.to_dict() for key, value in self.intervals.items()},
            "comparison": self.comparison.to_dict() if self.comparison else None,
            "discriminating": self.discriminating,
        }

    @property
    def notes(self) -> list[str]:
        return [self.comparison.sentence] if self.comparison else []


def analyse(
    results_by_model: dict[str, list[Any]],
    ranked_order: Sequence[str] | None = None,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    seed: int = 0,
) -> Analysis:
    """Intervals for every model, and a paired comparison of the top two."""
    scores = {key: per_case_scores(rows) for key, rows in results_by_model.items()}
    scores = {key: value for key, value in scores.items() if value}
    if not scores:
        return Analysis()

    analysis = Analysis(n_cases=max(len(v) for v in scores.values()))
    for key, case_scores in scores.items():
        interval = bootstrap_interval(
            list(case_scores.values()), resamples=resamples,
            confidence=confidence, seed=seed,
        )
        if interval is not None:
            analysis.intervals[key] = interval

    order = [key for key in (ranked_order or sorted(scores)) if key in scores]
    if len(order) >= 2:
        first, second = order[0], order[1]
        analysis.comparison = paired_comparison(
            scores[first], scores[second], first, second,
            resamples=resamples, confidence=confidence, seed=seed,
        )
        analysis.discriminating = discriminating_cases(scores[first], scores[second])
    return analysis
