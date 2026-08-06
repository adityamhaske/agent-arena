"""Pluggable accuracy scorers."""

from .base import FunctionScorer, Scorer, ScoreResult, ScoringContext, scorer
from .builtin import (
    BUILTIN_SCORERS,
    ClassificationScorer,
    CodeExecScorer,
    ContainsScorer,
    ExactMatchScorer,
    JsonMatchScorer,
    LLMJudgeScorer,
    ManualScorer,
    NumericScorer,
    RegexScorer,
    SemanticSimilarityScorer,
    extract_code,
    extract_json,
    normalize_text,
)
from .registry import ScorerRegistry, build_registry

__all__ = [
    "BUILTIN_SCORERS",
    "ClassificationScorer",
    "CodeExecScorer",
    "ContainsScorer",
    "ExactMatchScorer",
    "FunctionScorer",
    "JsonMatchScorer",
    "LLMJudgeScorer",
    "ManualScorer",
    "NumericScorer",
    "RegexScorer",
    "ScoreResult",
    "Scorer",
    "ScorerRegistry",
    "ScoringContext",
    "SemanticSimilarityScorer",
    "build_registry",
    "extract_code",
    "extract_json",
    "normalize_text",
    "scorer",
]
