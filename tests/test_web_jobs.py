"""Tests for the UI's background-run bookkeeping.

Two failures here are invisible until they hurt:

* `arena ui` is a long-running process, so a job table that only grows leaks
  every finished run — and its buffered feed — for as long as the server is
  left open;
* a run against a paid API that cannot be stopped keeps spending, and the
  only handle the browser has on it is the job id, so eviction must never
  reach a run that is still live.

These tests drive :class:`JobManager` with fake runs rather than real
evaluations: what is under test is retention and cancellation, not scoring.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from agent_arena.web.api import (
    LIVE_STATUSES,
    MAX_RETAINED_JOBS,
    ApiError,
    ArenaAPI,
    Job,
    JobManager,
)


class _Runs:
    """Starts jobs that finish, or hang, on command."""

    def __init__(self) -> None:
        self.manager = JobManager()
        self._release = threading.Event()

    def finished(self, project: str = "demo") -> Job:
        stopped = threading.Event()

        def target(job: Job) -> None:
            job.status = "done"
            job.finished_at = time.time()
            stopped.set()

        job = self.manager.start(project, target)
        assert stopped.wait(10), "the fake run never finished"
        return job

    def running(self, project: str = "live") -> Job:
        started = threading.Event()

        def target(job: Job) -> None:
            job.status = "running"
            started.set()
            self._release.wait(30)

        job = self.manager.start(project, target)
        assert started.wait(10), "the fake run never started"
        return job

    def close(self) -> None:
        self._release.set()


@pytest.fixture()
def runs():
    harness = _Runs()
    try:
        yield harness
    finally:
        harness.close()


def _retained(manager: JobManager, job_id: str) -> bool:
    try:
        manager.get(job_id)
    except ApiError:
        return False
    return True


class JobRetentionTests:
    def test_finished_runs_are_evicted_oldest_first_past_the_cap(self, runs):
        made = [runs.finished(f"p{index}") for index in range(MAX_RETAINED_JOBS + 10)]
        kept = [job.id for job in made if _retained(runs.manager, job.id)]

        # The cap is applied when a run starts, so the newest job can sit one
        # over it until the next start sweeps up.
        assert MAX_RETAINED_JOBS <= len(kept) <= MAX_RETAINED_JOBS + 1
        # Survivors are a suffix of what was started: the oldest went first.
        assert kept == [job.id for job in made[-len(kept):]]

    def test_nothing_is_forgotten_below_the_cap(self, runs):
        """A run the user just watched must still be there to re-open."""
        made = [runs.finished(f"p{index}") for index in range(MAX_RETAINED_JOBS)]
        assert [job.id for job in made if _retained(runs.manager, job.id)] == [
            job.id for job in made
        ]

    def test_a_live_run_is_never_evicted(self, runs):
        """Losing a running job's id would lose the only handle on the spend."""
        live = runs.running("live")
        for index in range(MAX_RETAINED_JOBS + 10):
            runs.finished(f"p{index}")

        assert live.status in LIVE_STATUSES
        assert runs.manager.get(live.id) is live
        assert runs.manager.active_for("live") is live

    def test_the_project_index_never_names_a_forgotten_job(self, runs):
        made = [runs.finished(f"p{index}") for index in range(MAX_RETAINED_JOBS + 10)]

        manager = runs.manager
        # White-box on purpose: a key pointing at a job that no longer exists
        # is exactly the leak the eviction is supposed to close.
        assert set(manager._by_project.values()) <= set(manager._jobs)  # noqa: SLF001
        assert not _retained(manager, made[0].id)
        assert manager.active_for("p0") is None

    def test_a_project_can_start_a_new_run_after_its_old_one_is_forgotten(self, runs):
        """Eviction must not leave a project looking permanently busy."""
        old = runs.finished("demo")
        for index in range(MAX_RETAINED_JOBS + 10):
            runs.finished(f"p{index}")

        assert not _retained(runs.manager, old.id)
        assert runs.manager.active_for("demo") is None
        assert runs.manager.start("demo", lambda job: None).id != old.id


class JobCancellationTests:
    def test_cancelling_raises_the_flag_the_runner_watches(self, runs):
        job = runs.running("live")
        assert job.snapshot()["cancel_requested"] is False

        assert runs.manager.cancel(job.id) is job
        assert job.cancel_event.is_set()
        assert job.snapshot()["cancel_requested"] is True

    def test_a_cancelled_run_is_still_live_until_it_winds_down(self, runs):
        """Cancelling asks; it does not pretend the calls have stopped."""
        job = runs.running("live")
        runs.manager.cancel(job.id)

        assert job.status in LIVE_STATUSES
        assert runs.manager.active_for("live") is job

    def test_cancel_run_answers_with_the_snapshot(self, tmp_path: Path):
        api = ArenaAPI(tmp_path / "projects")
        job = api.jobs.start("demo", lambda job: None)

        snapshot = api.cancel_run(job.id)
        assert snapshot["id"] == job.id
        assert snapshot["cancel_requested"] is True

    def test_cancelling_an_unknown_run_is_a_404_not_a_crash(self, tmp_path: Path):
        api = ArenaAPI(tmp_path / "projects")
        with pytest.raises(ApiError) as caught:
            api.cancel_run("nosuchjob")
        assert caught.value.status == 404
