"""Normalisation, weighting, constraints and ranking."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_arena.connectors.pricing import PriceBook
from agent_arena.core.config import ProjectConfig
from agent_arena.core.metrics import (
    aggregate_model,
    build_leaderboard,
    normalize,
    percentile,
)
from agent_arena.core.runner import CallResult

from .conftest import write_project


def make_config(tmp_path: Path, **sections) -> ProjectConfig:
    config = {"project": "m", "models": ["mock:oracle"], **sections}
    root = write_project(
        tmp_path / f"p{len(sections)}", config, [{"id": "a", "input": "q", "reference": "a"}]
    )
    return ProjectConfig.load(root)


def result(model_key: str, test_id: str, **kwargs) -> CallResult:
    defaults = dict(
        model=model_key,
        status="ok",
        score=1.0,
        passed=True,
        latency_ms=100.0,
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.001,
    )
    defaults.update(kwargs)
    return CallResult(model_key=model_key, test_id=test_id, **defaults)


# ---- normalisation ---------------------------------------------------------


def test_raw_mode_passes_a_zero_to_one_metric_through() -> None:
    assert normalize(0.83, mode="raw", direction="max", target=None, low=None, high=None) == 0.83


def test_minmax_scales_higher_is_better() -> None:
    kwargs = dict(mode="minmax", direction="max", target=None, low=0.5, high=1.0)
    assert normalize(1.0, **kwargs) == 1.0
    assert normalize(0.5, **kwargs) == 0.0
    assert normalize(0.75, **kwargs) == pytest.approx(0.5)


def test_minmax_inverts_lower_is_better() -> None:
    kwargs = dict(mode="minmax", direction="min", target=None, low=100.0, high=500.0)
    assert normalize(100.0, **kwargs) == 1.0
    assert normalize(500.0, **kwargs) == 0.0


def test_minmax_with_no_spread_gives_everyone_full_marks() -> None:
    """A metric nobody differs on must not swing the composite."""
    value = normalize(7.0, mode="minmax", direction="min", target=None, low=7.0, high=7.0)
    assert value == 1.0


def test_target_mode_for_cost_is_headroom_under_the_budget() -> None:
    kwargs = dict(mode="target", direction="min", target=10.0, low=None, high=None)
    assert normalize(0.0, **kwargs) == 1.0
    assert normalize(5.0, **kwargs) == pytest.approx(0.5)
    assert normalize(10.0, **kwargs) == 0.0
    assert normalize(25.0, **kwargs) == 0.0     # over budget bottoms out, never negative


def test_target_mode_for_a_max_metric_is_fraction_of_goal() -> None:
    kwargs = dict(mode="target", direction="max", target=0.9, low=None, high=None)
    assert normalize(0.9, **kwargs) == 1.0
    assert normalize(0.45, **kwargs) == pytest.approx(0.5)
    assert normalize(1.0, **kwargs) == 1.0      # exceeding the goal is still 1.0


def test_missing_values_stay_missing() -> None:
    assert normalize(None, mode="minmax", direction="min", target=None, low=0, high=1) is None


def test_percentile_interpolates() -> None:
    assert percentile([1, 2, 3, 4], 50) == pytest.approx(2.5)
    assert percentile([10], 95) == 10
    assert percentile([], 95) is None


# ---- aggregation -----------------------------------------------------------


def test_accuracy_is_weighted_by_test_weight() -> None:
    results = [
        result("m", "easy", score=0.0, passed=False),
        result("m", "important", score=1.0, passed=True),
    ]
    aggregate = aggregate_model(results, {"easy": 1.0, "important": 3.0})

    assert aggregate["raw"]["accuracy"] == pytest.approx(0.75)


def test_errors_are_excluded_from_accuracy_and_counted_as_unreliability() -> None:
    results = [
        result("m", "a", score=1.0),
        CallResult(model_key="m", model="m", test_id="b", status="error", error="boom"),
    ]
    aggregate = aggregate_model(results, {})

    assert aggregate["raw"]["accuracy"] == 1.0        # measured over completed calls only
    assert aggregate["raw"]["reliability"] == pytest.approx(0.5)
    assert aggregate["stats"]["errors"] == 1


def test_cost_is_reported_per_thousand_calls() -> None:
    aggregate = aggregate_model([result("m", "a", cost_usd=0.002)], {})

    assert aggregate["raw"]["cost"] == pytest.approx(2.0)
    assert aggregate["stats"]["cost_per_call_usd"] == pytest.approx(0.002)


def test_cost_is_unknown_when_any_call_is_unpriced() -> None:
    results = [result("m", "a", cost_usd=0.002), result("m", "b", cost_usd=None)]
    assert aggregate_model(results, {})["raw"]["cost"] is None


def test_custom_scorer_metrics_are_averaged() -> None:
    results = [
        result("m", "a", metrics={"similarity": 0.8}),
        result("m", "b", metrics={"similarity": 0.6}),
    ]
    assert aggregate_model(results, {})["raw"]["similarity"] == pytest.approx(0.7)


def test_accuracy_is_broken_down_by_tag() -> None:
    results = [
        result("m", "a", score=1.0, tags=["easy"]),
        result("m", "b", score=0.0, tags=["hard"]),
        result("m", "c", score=1.0, tags=["hard"]),
    ]
    by_tag = aggregate_model(results, {})["by_tag"]

    assert by_tag == {"easy": 1.0, "hard": pytest.approx(0.5)}


# ---- leaderboard -----------------------------------------------------------


class Spec:
    """Minimal stand-in for a ModelSpec."""

    def __init__(self, key: str, model: str = "mock:oracle", provider: str = "mock"):
        self.key, self.model, self.provider, self.card = key, model, provider, {}
        self.display = key


def test_composite_combines_weighted_normalised_metrics(tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        metrics={
            "weights": {"accuracy": 0.5, "latency": 0.5},
            "latency": {"target_ms": 1000},
        },
    )
    results = {
        "fast": [result("fast", "a", score=0.8, latency_ms=500)],
        "accurate": [result("accurate", "a", score=1.0, latency_ms=900)],
    }
    board = build_leaderboard(
        config, results, [Spec("fast"), Spec("accurate")], PriceBook()
    )

    # fast:     0.5*0.8 + 0.5*(1 - 500/1000)  = 0.40 + 0.25 = 0.65
    # accurate: 0.5*1.0 + 0.5*(1 - 900/1000)  = 0.50 + 0.05 = 0.55
    assert board.get("fast").composite == pytest.approx(0.65)
    assert board.get("accurate").composite == pytest.approx(0.55)
    assert board.winner.key == "fast"


def test_missing_metric_redistributes_its_weight_rather_than_scoring_zero(tmp_path: Path) -> None:
    config = make_config(
        tmp_path, metrics={"weights": {"accuracy": 0.5, "cost": 0.5}}
    )
    results = {"unpriced": [result("unpriced", "a", score=0.9, cost_usd=None)]}
    board = build_leaderboard(config, results, [Spec("unpriced")], PriceBook())
    entry = board.get("unpriced")

    assert entry.composite == pytest.approx(0.9)   # not 0.45
    assert any("redistributed" in w for w in entry.warnings)


def test_hard_constraint_disqualifies_rather_than_penalises(tmp_path: Path) -> None:
    config = make_config(tmp_path, constraints={"min_accuracy": 0.9})
    results = {
        "good": [result("good", "a", score=1.0)],
        "bad": [result("bad", "a", score=0.5)],
    }
    board = build_leaderboard(config, results, [Spec("good"), Spec("bad")], PriceBook())

    assert board.get("bad").status == "failed"
    assert board.get("bad").composite is None
    assert "below the required" in board.get("bad").failures[0]
    assert [e.key for e in board.ranked] == ["good"]


def test_disqualified_models_do_not_stretch_the_minmax_scale(tmp_path: Path) -> None:
    """A failing outlier must not change how the qualifying models compare."""
    config = make_config(
        tmp_path,
        metrics={"weights": {"latency": 1.0}},
        constraints={"min_accuracy": 0.5},
    )
    specs = [Spec("a"), Spec("b"), Spec("outlier")]
    results = {
        "a": [result("a", "t", score=1.0, latency_ms=100)],
        "b": [result("b", "t", score=1.0, latency_ms=200)],
        "outlier": [result("outlier", "t", score=0.0, latency_ms=99999)],
    }
    board = build_leaderboard(config, results, specs, PriceBook())

    assert board.get("a").metrics["latency"].normalized == 1.0
    assert board.get("b").metrics["latency"].normalized == 0.0
    assert board.get("outlier").status == "failed"


def test_missing_capability_disqualifies(tmp_path: Path) -> None:
    config = make_config(
        tmp_path, constraints={"deployment": {"required_features": ["vision"]}}
    )
    book = PriceBook()
    book.merge_overrides("no-vision", {"features": ["streaming"], "input_usd_per_mtok": 1,
                                       "output_usd_per_mtok": 1})
    results = {"m": [result("m", "a")]}
    board = build_leaderboard(config, results, [Spec("m", model="no-vision")], book)

    assert board.get("m").status == "failed"
    assert "vision" in board.get("m").failures[0]


def test_undeclared_privacy_fails_the_gate(tmp_path: Path) -> None:
    """Not-declared must not read as satisfied for a compliance requirement."""
    config = make_config(tmp_path, constraints={"privacy": {"required": ["dpa"]}})
    book = PriceBook()
    book.merge_overrides("silent", {"input_usd_per_mtok": 1, "output_usd_per_mtok": 1})
    board = build_leaderboard(
        config, {"m": [result("m", "a")]}, [Spec("m", model="silent")], book
    )

    assert board.get("m").status == "failed"
    assert "privacy" in board.get("m").failures[0]


def test_declared_privacy_passes_the_gate(tmp_path: Path) -> None:
    config = make_config(tmp_path, constraints={"privacy": {"required": ["dpa"]}})
    book = PriceBook()
    book.merge_overrides(
        "compliant",
        {"input_usd_per_mtok": 1, "output_usd_per_mtok": 1, "privacy": {"dpa": True}},
    )
    board = build_leaderboard(
        config, {"m": [result("m", "a")]}, [Spec("m", model="compliant")], book
    )

    assert board.get("m").status == "ranked"


def test_model_with_no_results_is_marked_no_data(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    board = build_leaderboard(config, {}, [Spec("absent")], PriceBook())

    assert board.get("absent").status == "no_data"
    assert board.winner is None


def test_notes_flag_unweighted_errors(tmp_path: Path) -> None:
    config = make_config(tmp_path, metrics={"weights": {"accuracy": 1.0}})
    results = {
        "m": [
            result("m", "a"),
            CallResult(model_key="m", model="m", test_id="b", status="error", error="x"),
        ]
    }
    board = build_leaderboard(config, results, [Spec("m")], PriceBook())

    assert any("reliability" in note for note in board.notes)


def test_notes_flag_a_photo_finish(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    results = {
        "a": [result("a", "t", score=0.900)],
        "b": [result("b", "t", score=0.895)],
    }
    board = build_leaderboard(config, results, [Spec("a"), Spec("b")], PriceBook())

    assert any("within noise" in note for note in board.notes)
