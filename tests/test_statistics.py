"""Tests for confidence intervals and the paired comparison.

The project's central claim is that it does not assert more than the evidence
supports, so the tests that matter are the ones asserting it stays *quiet*: a
tiny sample must produce no interval at all, two models a point apart on twelve
cases must not be separated, and a difference too small to chase must not
produce a fake "collect N more cases" number.

Everything resamples over cases rather than trials, and every function takes a
seed, so these assertions are exact rather than flaky.
"""

from __future__ import annotations

import pytest

from agent_arena.core import statistics as st


class _Result:
    """The parts of a CallResult the statistics layer reads."""

    def __init__(self, test_id, score, status="ok"):
        self.test_id = test_id
        self.score = score
        self.status = status


# ------------------------------------------------------------ per-case means


def test_trials_are_averaged_rather_than_counted_as_extra_evidence():
    # Counting trials as samples would shrink every interval by a factor the
    # data does not support: they measure consistency, not generalisation.
    results = [_Result("t1", 1.0), _Result("t1", 0.0), _Result("t2", 1.0)]
    assert st.per_case_scores(results) == {"t1": 0.5, "t2": 1.0}


def test_errored_calls_are_excluded():
    results = [_Result("t1", 1.0), _Result("t2", 0.0, status="error")]
    assert st.per_case_scores(results) == {"t1": 1.0}


def test_unscored_calls_are_excluded():
    assert st.per_case_scores([_Result("t1", None)]) == {}


# -------------------------------------------------------------- the interval


def test_a_tiny_sample_gets_no_interval():
    # An interval from one or two points is arithmetic, not evidence, and
    # printing it would imply precision that does not exist.
    assert st.bootstrap_interval([1.0]) is None
    assert st.bootstrap_interval([1.0, 0.0]) is None


def test_an_interval_brackets_the_mean():
    scores = [1.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0]
    interval = st.bootstrap_interval(scores, seed=1)
    assert interval.low <= interval.point <= interval.high


def test_a_unanimous_sample_has_a_zero_width_interval():
    interval = st.bootstrap_interval([1.0] * 10, seed=1)
    assert interval.point == 1.0 and interval.width == 0.0


def test_more_cases_give_a_narrower_interval():
    # The property that makes "collect more cases" real advice.
    pattern = [1.0, 0.0]
    narrow = st.bootstrap_interval(pattern * 100, seed=3)
    wide = st.bootstrap_interval(pattern * 5, seed=3)
    assert narrow.width < wide.width


def test_intervals_are_reproducible_from_a_seed():
    scores = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0]
    assert st.bootstrap_interval(scores, seed=7) == st.bootstrap_interval(scores, seed=7)


# ------------------------------------------------------------- the comparison


def test_a_clear_winner_is_separated():
    a = {f"t{i}": 1.0 for i in range(30)}
    b = {f"t{i}": 0.0 for i in range(30)}
    comparison = st.paired_comparison(a, b, "a", "b", seed=1)
    assert comparison.separated is True
    assert "more accurate" in comparison.sentence


def test_two_models_a_point_apart_are_not_separated():
    a = {f"t{i}": 1.0 if i < 10 else 0.0 for i in range(12)}
    b = {f"t{i}": 1.0 if i < 9 else 0.0 for i in range(12)}
    comparison = st.paired_comparison(a, b, "a", "b", seed=1)
    assert comparison.separated is False
    assert "too close to call" in comparison.sentence


def test_the_sentence_names_accuracy_so_it_is_not_misread():
    # The leaderboard ranks on the composite, which also weighs cost and
    # latency. "Indistinguishable" without the word accuracy reads as "the
    # ranking is meaningless", which is usually the opposite of the truth.
    a = {f"t{i}": 1.0 if i < 10 else 0.0 for i in range(12)}
    b = {f"t{i}": 1.0 if i < 9 else 0.0 for i in range(12)}
    sentence = st.paired_comparison(a, b, "a", "b", seed=1).sentence
    assert "accuracy" in sentence
    assert "cost and speed" in sentence


def test_identical_models_are_never_separated():
    a = {f"t{i}": float(i % 2) for i in range(20)}
    comparison = st.paired_comparison(a, dict(a), "a", "b", seed=1)
    assert comparison.separated is False
    assert comparison.wins == comparison.losses == 0


def test_wins_losses_and_ties_add_up():
    a = {"t1": 1.0, "t2": 0.0, "t3": 1.0}
    b = {"t1": 0.0, "t2": 1.0, "t3": 1.0}
    comparison = st.paired_comparison(a, b, "a", "b", seed=1)
    assert (comparison.wins, comparison.losses, comparison.ties) == (1, 1, 1)


def test_a_comparison_needs_at_least_three_shared_cases():
    assert st.paired_comparison({"t1": 1.0}, {"t1": 0.0}) is None


def test_only_shared_cases_are_compared():
    a = {"t1": 1.0, "t2": 1.0, "t3": 1.0, "only_a": 0.0}
    b = {"t1": 0.0, "t2": 0.0, "t3": 0.0, "only_b": 1.0}
    comparison = st.paired_comparison(a, b, "a", "b", seed=1)
    assert comparison.wins + comparison.losses + comparison.ties == 3


# ------------------------------------------------------------------- power


def test_the_power_calculation_is_actionable():
    a = {f"t{i}": 1.0 if i < 8 else 0.0 for i in range(12)}
    b = {f"t{i}": 1.0 if i < 6 else 0.0 for i in range(12)}
    comparison = st.paired_comparison(a, b, "a", "b", seed=1)
    if not comparison.separated:
        assert comparison.cases_needed is None or comparison.cases_needed > 12


def test_a_hopeless_difference_gets_no_number_rather_than_a_silly_one():
    # Telling someone to collect 40,000 cases is not advice.
    deltas = [0.0] * 20
    assert st.cases_to_separate(deltas) is None


def test_the_power_calculation_needs_a_real_sample():
    assert st.cases_to_separate([0.5, -0.5]) is None


# --------------------------------------------------------- discriminating


def test_discriminating_cases_are_where_the_models_disagree():
    a = {"t1": 1.0, "t2": 1.0, "t3": 0.0}
    b = {"t1": 1.0, "t2": 0.0, "t3": 0.0}
    rows = st.discriminating_cases(a, b)
    assert [row["test_id"] for row in rows] == ["t2"]


def test_agreeing_cases_carry_no_information_and_are_omitted():
    a = b = {f"t{i}": 1.0 for i in range(5)}
    assert st.discriminating_cases(a, dict(b)) == []


# -------------------------------------------------------------- the analysis


def test_analyse_produces_intervals_and_a_comparison():
    by_model = {
        "a": [_Result(f"t{i}", 1.0 if i < 25 else 0.0) for i in range(30)],
        "b": [_Result(f"t{i}", 1.0 if i < 10 else 0.0) for i in range(30)],
    }
    analysis = st.analyse(by_model, ranked_order=["a", "b"], seed=1)
    assert set(analysis.intervals) == {"a", "b"}
    assert analysis.comparison.separated is True
    assert analysis.n_cases == 30
    assert analysis.to_dict()["comparison"]["a"] == "a"


def test_analyse_on_a_single_model_reports_no_comparison():
    analysis = st.analyse({"a": [_Result(f"t{i}", 1.0) for i in range(5)]}, seed=1)
    assert analysis.comparison is None
    assert analysis.notes == []


def test_analyse_with_nothing_scored_is_empty_rather_than_raising():
    assert st.analyse({}).to_dict()["intervals"] == {}
