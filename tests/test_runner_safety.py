"""Tests for the two ways a run is allowed to stop early.

Both exist because an evaluation spends real money while it runs. Before them,
a misconfigured sweep against a paid API could not be stopped from the browser
at all, and a budget could be declared in config but never enforced.

The property that matters in both cases is not just that the run halts — it is
that the partial results survive and are *labelled* partial. A truncated sweep
presented as a complete leaderboard is exactly the quiet lie this project
exists to avoid.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from agent_arena.core.config import ProjectConfig
from agent_arena.core.runner import ArenaRunner

PLANNED = 60  # 30 cases x 2 trials x 1 model


@pytest.fixture()
def project(tmp_path: Path):
    (tmp_path / "tests.yaml").write_text(
        json.dumps(
            {"tests": [{"id": f"t{i}", "input": f"case {i}", "reference": "billing"}
                       for i in range(30)]}
        ),
        encoding="utf-8",
    )

    def build(budgets=None):
        return ProjectConfig.from_dict(
            {
                "project": "safety_probe",
                "models": [
                    {
                        "key": "m1",
                        "model": "mock:probe",
                        "params": {"mode": "flaky", "accuracy": 90},
                        # Priced high so a small cap is crossed quickly.
                        "card": {"input_usd_per_mtok": 1000, "output_usd_per_mtok": 5000},
                    }
                ],
                "run": {"trials": 2, "concurrency": 2},
                "scorers": {
                    "default": "classification",
                    "options": {"classification": {"labels": ["billing", "technical"]}},
                },
                "tests": ["tests.yaml"],
                "output": {"dir": "results"},
                "budgets": budgets or {},
            },
            root=tmp_path,
        )

    return build


# ------------------------------------------------------------------ baseline


def test_without_a_budget_the_whole_sweep_runs(project):
    result = ArenaRunner(project()).run()
    assert len(result.results) == PLANNED
    assert result.leaderboard.notes == []


# ------------------------------------------------------------------- budgets


def test_a_run_budget_stops_the_sweep(project):
    result = ArenaRunner(project({"max_run_usd": 0.02})).run()
    assert len(result.results) < PLANNED


def test_a_stopped_run_says_its_results_are_partial(project):
    result = ArenaRunner(project({"max_run_usd": 0.02})).run()
    notes = " ".join(result.leaderboard.notes)
    assert "partial" in notes
    assert "budget" in notes


def test_a_stopped_run_keeps_what_it_already_paid_for(project):
    # Throwing away collected answers would waste the spend without saving any.
    result = ArenaRunner(project({"max_run_usd": 0.02})).run()
    assert result.results
    assert result.run_id


def test_on_exceed_warn_does_not_stop_the_run(project):
    result = ArenaRunner(project({"max_run_usd": 0.02, "on_exceed": "warn"})).run()
    assert len(result.results) == PLANNED


def test_a_per_model_budget_stops_the_sweep(project):
    result = ArenaRunner(project({"max_model_usd": 0.02})).run()
    assert len(result.results) < PLANNED
    assert "per-model" in " ".join(result.leaderboard.notes)


def test_a_budget_that_is_never_reached_changes_nothing(project):
    result = ArenaRunner(project({"max_run_usd": 1000.0})).run()
    assert len(result.results) == PLANNED
    assert result.leaderboard.notes == []


# -------------------------------------------------------------- cancellation


def test_a_cancel_event_stops_the_sweep(project):
    event = threading.Event()
    runner = ArenaRunner(project(), cancel_event=event)

    original, seen = runner._execute, {"n": 0}  # noqa: SLF001

    def counted(*args, **kwargs):
        seen["n"] += 1
        if seen["n"] >= 8:
            event.set()
        return original(*args, **kwargs)

    runner._execute = counted  # noqa: SLF001
    result = runner.run()

    assert len(result.results) < PLANNED
    assert "cancelled" in " ".join(result.leaderboard.notes)


def test_a_cancel_set_before_the_run_stops_it_almost_immediately(project):
    event = threading.Event()
    event.set()
    result = ArenaRunner(project(), cancel_event=event).run()
    assert len(result.results) < PLANNED


def test_an_untouched_cancel_event_does_not_interfere(project):
    result = ArenaRunner(project(), cancel_event=threading.Event()).run()
    assert len(result.results) == PLANNED


def test_a_runner_built_without_a_cancel_event_still_works(project):
    # The default must be a live Event, not None, or every completion check
    # would raise on the attribute.
    runner = ArenaRunner(project())
    assert runner.cancel_event is not None
    assert not runner.cancel_event.is_set()
