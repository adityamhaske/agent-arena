"""Tests for continuing an interrupted run.

A sweep that dies at 90% has already paid for those calls. Starting over spends
the money a second time for answers that are already in the database, which is
the whole reason this exists — so the test that matters is not "does it finish"
but "how many calls did it actually make the second time".

Only a successful call is skipped. An errored one is exactly what a resume is
meant to retry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_arena.core.config import ProjectConfig
from agent_arena.core.errors import ConfigError
from agent_arena.core.runner import ArenaRunner
from agent_arena.core.store import ResultStore

PLANNED = 20  # 10 cases x 2 trials x 1 model


@pytest.fixture()
def project(tmp_path: Path):
    (tmp_path / "tests.yaml").write_text(
        json.dumps(
            {"tests": [{"id": f"t{i}", "input": f"case {i}", "reference": "billing"}
                       for i in range(10)]}
        ),
        encoding="utf-8",
    )
    return ProjectConfig.from_dict(
        {
            "project": "resume_probe",
            "models": [{"key": "m1", "model": "mock:oracle"}],
            "run": {"trials": 2, "concurrency": 2},
            "scorers": {"default": "classification",
                        "options": {"classification": {"labels": ["billing", "technical"]}}},
            "tests": ["tests.yaml"],
            "output": {"dir": "results"},
        },
        root=tmp_path,
    )


def _count_calls(runner: ArenaRunner) -> int:
    """Wrap _execute so we can see how many real calls a run made."""
    original = runner._execute  # noqa: SLF001
    counter = {"n": 0}

    def counted(*args, **kwargs):
        counter["n"] += 1
        return original(*args, **kwargs)

    runner._execute = counted  # noqa: SLF001
    return counter


def test_resuming_a_finished_run_makes_no_calls_at_all(project):
    first = ArenaRunner(project).run()
    assert len(first.results) == PLANNED

    runner = ArenaRunner(project, resume_run_id=first.run_id)
    counter = _count_calls(runner)
    second = runner.run()

    assert counter["n"] == 0, "a completed run should cost nothing to resume"
    assert len(second.results) == PLANNED
    assert second.run_id == first.run_id


def test_resuming_a_partial_run_only_fills_the_gap(project):
    import threading

    event = threading.Event()
    runner = ArenaRunner(project, cancel_event=event)
    original = runner._execute  # noqa: SLF001
    seen = {"n": 0}

    def counted(*args, **kwargs):
        seen["n"] += 1
        if seen["n"] >= 6:
            event.set()
        return original(*args, **kwargs)

    runner._execute = counted  # noqa: SLF001
    partial = runner.run()
    done_first = len(partial.results)
    assert 0 < done_first < PLANNED

    resumed = ArenaRunner(project, resume_run_id=partial.run_id)
    counter = _count_calls(resumed)
    final = resumed.run()

    assert counter["n"] == PLANNED - done_first
    assert len(final.results) == PLANNED


def test_a_resumed_run_keeps_its_original_id(project):
    first = ArenaRunner(project).run()
    second = ArenaRunner(project, resume_run_id=first.run_id).run()
    assert second.run_id == first.run_id


def test_resuming_a_run_that_does_not_exist_says_how_to_find_one(project):
    ArenaRunner(project).run()  # so a database exists
    with pytest.raises(ConfigError) as exc:
        ArenaRunner(project, resume_run_id="run_not_real").run()
    assert "arena runs" in str(exc.value)


def test_resuming_another_projects_run_is_refused(project, tmp_path):
    first = ArenaRunner(project).run()
    with ResultStore(project.database) as store:
        store._conn.execute(  # noqa: SLF001
            "UPDATE runs SET project = 'somewhere_else' WHERE run_id = ?", (first.run_id,)
        )
        store._conn.commit()  # noqa: SLF001
    with pytest.raises(ConfigError, match="belongs to project"):
        ArenaRunner(project, resume_run_id=first.run_id).run()


def test_an_errored_call_is_retried_rather_than_skipped(project):
    first = ArenaRunner(project).run()
    with ResultStore(project.database) as store:
        store._conn.execute(  # noqa: SLF001
            "UPDATE results SET status = 'error', error = 'timeout' "
            "WHERE run_id = ? AND test_id = 't0'",
            (first.run_id,),
        )
        store._conn.commit()  # noqa: SLF001

    runner = ArenaRunner(project, resume_run_id=first.run_id)
    counter = _count_calls(runner)
    runner.run()
    # Two trials of t0 were marked failed; both should be attempted again.
    assert counter["n"] == 2
