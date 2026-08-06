"""Built-in scorers and the custom-scorer registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_arena.core.errors import ScorerError
from agent_arena.core.testcase import TestCase
from agent_arena.scorers import ScoreResult, ScoringContext, extract_code, extract_json
from agent_arena.scorers.registry import ScorerRegistry


def ctx(**params) -> ScoringContext:
    return ScoringContext(
        test_case=TestCase(id="t", input="q", reference=None, params=params),
        options={},
    )


def score(name: str, output: str, reference, **params) -> ScoreResult:
    return ScorerRegistry().get(name)(output, reference, ctx(**params))


# ---- exact_match -----------------------------------------------------------


def test_exact_match_ignores_case_punctuation_and_spacing() -> None:
    assert score("exact_match", "  Refund. ", "refund").passed is True


def test_exact_match_can_be_strict() -> None:
    result = score("exact_match", "Refund", "refund", case_sensitive=True)
    assert result.passed is False


def test_exact_match_accepts_any_of_a_list() -> None:
    assert score("exact_match", "billing", ["refund", "billing"]).passed is True


# ---- contains --------------------------------------------------------------


def test_contains_all_needles_gives_partial_credit() -> None:
    result = score("contains", "alpha and beta", ["alpha", "beta", "gamma"])
    assert result.score == pytest.approx(2 / 3)
    assert result.passed is False


def test_contains_any_mode() -> None:
    assert score("contains", "alpha only", ["alpha", "zeta"], mode="any").passed is True


# ---- regex -----------------------------------------------------------------


def test_regex_matches_and_reports_capture() -> None:
    result = score("regex", "order 8821 shipped", r"order (\d+)", expect_group="8821")
    assert result.passed is True
    assert result.detail["captured"] == "8821"


def test_invalid_regex_raises_scorer_error() -> None:
    with pytest.raises(ScorerError, match="invalid regex"):
        score("regex", "x", "(unclosed")


# ---- classification --------------------------------------------------------


def test_classification_picks_the_named_label() -> None:
    result = score(
        "classification", "This goes to billing.", "billing",
        labels=["billing", "technical", "spam"],
    )
    assert result.passed is True
    assert result.detail["predicted"] == "billing"


def test_classification_needs_labels() -> None:
    with pytest.raises(ScorerError, match="needs a 'labels' list"):
        score("classification", "billing", "billing")


def test_classification_fails_when_no_label_is_named() -> None:
    result = score("classification", "hmm not sure", "billing", labels=["billing", "spam"])
    assert result.passed is False
    assert "named none of the labels" in result.reason


# ---- numeric ---------------------------------------------------------------


def test_numeric_extracts_and_compares_with_tolerance() -> None:
    assert score("numeric", "The total is 1,299.00 dollars", 1299).passed is True
    assert score("numeric", "about 1300", 1299, abs_tol=5).passed is True
    assert score("numeric", "about 1400", 1299, abs_tol=5).passed is False


def test_numeric_with_no_number_fails_cleanly() -> None:
    result = score("numeric", "no digits here", 5)
    assert result.passed is False
    assert "no number" in result.reason


# ---- json_match ------------------------------------------------------------


def test_json_match_subset_ignores_extra_keys() -> None:
    result = score(
        "json_match", '{"a": 1, "b": "x", "extra": true}', {"a": 1, "b": "x"}
    )
    assert result.passed is True


def test_json_match_scores_partial_key_agreement() -> None:
    result = score("json_match", '{"a": 1, "b": "wrong"}', {"a": 1, "b": "x"})
    assert result.score == pytest.approx(0.5)
    assert result.detail["mismatched"] == ["b"]


def test_json_match_handles_fenced_output() -> None:
    fenced = '```json\n{"a": 1}\n```'
    assert score("json_match", fenced, {"a": 1}).passed is True


def test_json_match_rejects_non_json() -> None:
    result = score("json_match", "definitely not json", {"a": 1})
    assert result.passed is False
    assert "not valid JSON" in result.reason


# ---- semantic --------------------------------------------------------------


def test_semantic_lexical_similarity_matches_paraphrase() -> None:
    result = score(
        "semantic",
        "The parcel was delivered to the customer yesterday",
        "The customer received the parcel yesterday",
        threshold=0.4,
    )
    assert result.passed is True
    assert 0 < result.detail["similarity"] <= 1
    assert result.detail["method"] == "lexical"


def test_semantic_uses_a_custom_embedding_when_given(tmp_path: Path) -> None:
    module = tmp_path / "embed.py"
    module.write_text(
        "def embed(text):\n"
        "    return [float(text.count(c)) for c in 'abcdefghijklmnopqrstuvwxyz']\n",
        encoding="utf-8",
    )
    context = ScoringContext(
        test_case=TestCase(
            id="t", input="q", params={"embedding": f"{module}:embed", "threshold": 0.9}
        ),
        project_root=tmp_path,
    )
    result = ScorerRegistry().get("semantic")("abc abc", "abc abc", context)

    assert result.detail["method"] == "embedding"
    assert result.score == pytest.approx(1.0)


# ---- llm_judge -------------------------------------------------------------


def test_llm_judge_parses_a_json_verdict() -> None:
    context = ScoringContext(
        test_case=TestCase(id="t", input="q"),
        judge=lambda prompt, system=None: '{"score": 0.8, "passed": true, "reason": "close"}',
    )
    result = ScorerRegistry().get("llm_judge")("an answer", "the answer", context)

    assert result.score == pytest.approx(0.8)
    assert result.passed is True
    assert result.reason == "close"


def test_llm_judge_falls_back_to_pass_fail_keywords() -> None:
    context = ScoringContext(
        test_case=TestCase(id="t", input="q"),
        judge=lambda prompt, system=None: "PASS — matches the reference",
    )
    assert ScorerRegistry().get("llm_judge")("a", "b", context).passed is True


def test_llm_judge_without_a_judge_explains_the_fix() -> None:
    with pytest.raises(ScorerError, match="needs a judge model"):
        ScorerRegistry().get("llm_judge")("a", "b", ScoringContext(test_case=TestCase(id="t", input="q")))


# ---- code_exec -------------------------------------------------------------


def test_code_exec_runs_generated_code_against_assertions() -> None:
    output = "```python\ndef add(a, b):\n    return a + b\n```"
    result = score("code_exec", output, "assert add(2, 3) == 5")
    assert result.passed is True
    assert result.detail["returncode"] == 0


def test_code_exec_fails_on_a_wrong_implementation() -> None:
    output = "def add(a, b):\n    return a * b"
    result = score("code_exec", output, "assert add(2, 3) == 5")
    assert result.passed is False
    assert "AssertionError" in result.detail["stderr"]


def test_code_exec_times_out_rather_than_hanging() -> None:
    output = "import time\ntime.sleep(30)"
    result = score("code_exec", output, "assert True", timeout_s=1)
    assert result.passed is False
    assert result.detail["timeout"] is True


def test_code_exec_rejects_other_languages() -> None:
    with pytest.raises(ScorerError, match="python only"):
        score("code_exec", "puts 1", "assert true", language="ruby")


# ---- helpers ---------------------------------------------------------------


def test_extract_json_handles_prose_wrapping() -> None:
    assert extract_json('Here you go: {"a": 1} — hope that helps') == {"a": 1}


def test_extract_json_returns_none_for_garbage() -> None:
    assert extract_json("no json at all") is None


def test_extract_code_prefers_the_requested_fence() -> None:
    text = "```sql\nSELECT 1\n```\n```python\nx = 1\n```"
    assert extract_code(text, "python") == "x = 1"


def test_score_result_clamps_out_of_range_scores() -> None:
    assert ScoreResult(score=7.0).score == 1.0
    assert ScoreResult(score=-3.0).score == 0.0


def test_score_result_infers_passed_from_score() -> None:
    assert ScoreResult(score=0.7).passed is True
    assert ScoreResult(score=0.2).passed is False


# ---- registry --------------------------------------------------------------


CUSTOM_SCORER = '''
from agent_arena.scorers import Scorer, ScoreResult, scorer


class ShoutScorer(Scorer):
    name = "shout"
    requires_reference = False

    def score(self, output, reference, context):
        loud = output.isupper()
        return ScoreResult(score=1.0 if loud else 0.0, passed=loud)


@scorer("starts_with")
def starts_with(output, reference, context):
    hit = output.startswith(str(reference))
    return ScoreResult(score=1.0 if hit else 0.0, passed=hit)
'''


def test_registry_loads_custom_scorers_from_a_folder(tmp_path: Path) -> None:
    folder = tmp_path / "scorers"
    folder.mkdir()
    (folder / "custom.py").write_text(CUSTOM_SCORER, encoding="utf-8")

    registry = ScorerRegistry()
    registry.load_paths([folder])

    assert "shout" in registry
    assert "starts_with" in registry
    assert registry.get("shout")("LOUD", None, ctx()).passed is True
    assert registry.get("starts_with")("hello world", "hello", ctx()).passed is True


def test_registry_reports_unknown_eval_types_with_the_options(tmp_path: Path) -> None:
    with pytest.raises(ScorerError, match="unknown eval_type 'nope'"):
        ScorerRegistry().get("nope")


def test_registry_rejects_a_module_defining_nothing(tmp_path: Path) -> None:
    empty = tmp_path / "empty.py"
    empty.write_text("x = 1\n", encoding="utf-8")

    with pytest.raises(ScorerError, match="defines no scorers"):
        ScorerRegistry().load_module(empty)


def test_registry_applies_configured_options() -> None:
    registry = ScorerRegistry(options={"semantic": {"note": "unused-but-accepted"}})
    assert registry.get("semantic").options == {"note": "unused-but-accepted"}


def test_two_projects_can_define_the_same_module_name(tmp_path: Path) -> None:
    """Project-local plugins must not collide in sys.modules."""
    for name, label in (("a", "alpha"), ("b", "beta")):
        folder = tmp_path / name / "scorers"
        folder.mkdir(parents=True)
        (folder / "shared.py").write_text(
            "from agent_arena.scorers import Scorer, ScoreResult\n\n"
            "class S(Scorer):\n"
            f"    name = '{label}'\n"
            "    def score(self, output, reference, context):\n"
            "        return ScoreResult(score=1.0)\n",
            encoding="utf-8",
        )
    first, second = ScorerRegistry(), ScorerRegistry()
    first.load_paths([tmp_path / "a" / "scorers"])
    second.load_paths([tmp_path / "b" / "scorers"])

    assert "alpha" in first and "alpha" not in second
    assert "beta" in second and "beta" not in first
