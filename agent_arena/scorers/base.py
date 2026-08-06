"""Scorer contract.

A scorer turns one model output into a number in ``[0, 1]``. Everything a
project needs to grade its own domain sits behind this one method, so the
runner never needs to know whether it is comparing labels, JSON, or the exit
code of generated code.

Custom scorers live in the project folder and are picked up automatically::

    # projects/my_project/scorers/tone.py
    from agent_arena.scorers import Scorer, ScoreResult

    class ToneScorer(Scorer):
        name = "tone"

        def score(self, output, reference, context):
            polite = "please" in output.lower()
            return ScoreResult(score=1.0 if polite else 0.0, passed=polite)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from ..core.errors import ScorerError


@dataclass
class ScoreResult:
    """The verdict on a single model output.

    ``score`` drives the accuracy metric; ``metrics`` lets a scorer emit any
    extra project-specific number, which the config can then weight by name in
    the composite exactly like a builtin.
    """

    score: float
    passed: bool | None = None
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            self.score = float(self.score)
        except (TypeError, ValueError) as exc:
            raise ScorerError(f"scorer returned a non-numeric score: {self.score!r}") from exc
        # Clamping keeps one misbehaving scorer from silently dominating the
        # weighted composite for every other metric.
        self.score = max(0.0, min(1.0, self.score))
        if self.passed is None:
            self.passed = self.score >= 0.5


@dataclass
class ScoringContext:
    """Everything a scorer may need beyond the output and the reference."""

    test_case: Any = None
    model_key: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    judge: Callable[..., str] | None = None
    """Callable ``(prompt, system=None) -> str`` bound to the project's judge model."""

    project_root: Any = None

    @property
    def params(self) -> dict[str, Any]:
        """Scorer options merged with the test case's own ``params`` (case wins)."""
        merged = dict(self.options)
        case_params = getattr(self.test_case, "params", None)
        if isinstance(case_params, dict):
            merged.update(case_params)
        return merged


class Scorer(ABC):
    """Base class for all scorers."""

    name: str = ""
    requires_reference: bool = True
    description: str = ""

    def __init__(self, **options: Any) -> None:
        self.options = options

    @abstractmethod
    def score(self, output: str, reference: Any, context: ScoringContext) -> ScoreResult:
        """Grade ``output`` against ``reference``. Must return a ``ScoreResult``."""

    def __call__(self, output: str, reference: Any, context: ScoringContext) -> ScoreResult:
        result = self.score(output, reference, context)
        if not isinstance(result, ScoreResult):
            # Tolerate the two shapes people reach for first.
            if isinstance(result, (int, float)):
                result = ScoreResult(score=float(result))
            elif isinstance(result, bool):
                result = ScoreResult(score=1.0 if result else 0.0, passed=result)
            else:
                raise ScorerError(
                    f"{type(self).__name__}.score must return a ScoreResult "
                    f"(or a number/bool), got {type(result).__name__}"
                )
        return result

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} name={self.name!r}>"


class FunctionScorer(Scorer):
    """Adapter so a plain function can be registered as a scorer."""

    def __init__(self, fn: Callable[..., Any], name: str, **options: Any) -> None:
        super().__init__(**options)
        self._fn = fn
        self.name = name
        self.description = (fn.__doc__ or "").strip().split("\n")[0]

    def score(self, output: str, reference: Any, context: ScoringContext) -> ScoreResult:
        return self._fn(output, reference, context)


def scorer(name: str, requires_reference: bool = True):
    """Decorator registering a function as a named scorer.

    ::

        @scorer("has_citation", requires_reference=False)
        def has_citation(output, reference, context):
            return ScoreResult(score=1.0 if "[" in output else 0.0)
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn._arena_scorer_name = name  # type: ignore[attr-defined]
        fn._arena_requires_reference = requires_reference  # type: ignore[attr-defined]
        return fn

    return decorator
