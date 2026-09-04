"""Tests for deleting things.

This is the code that removes a user's data, so the tests here are weighted
towards the ways that goes wrong rather than the ways it goes right:

* **path traversal**, because a project name and a run id both arrive from an
  HTTP request and both end up in a path something is about to unlink;
* **dry_run fidelity**, because the plan a confirmation dialog shows and the
  work the real call does come from one function, and if they could diverge the
  dialog would be lying about what is about to happen;
* **soft-delete completeness**, because a deleted run that reappears in history
  or in a trend is the classic way this feature is subtly broken.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agent_arena.core.store import ResultStore
from agent_arena.service import projects, runs
from agent_arena.service.errors import NotFoundError, ServiceError
from agent_arena.service.paths import resolve_within, safe_name

EXAMPLE = Path("projects/support_triage")


def _seed_run(project_dir):
    """Give the copied project a run to act on.

    The tests used to assume `projects/support_triage/results/` existed. It does
    on a machine where sweeps have been run, and it is gitignored — so the suite
    passed locally and failed on every fresh checkout. Producing the run here
    makes each test self-contained. It is offline and costs nothing: the example
    project is all `mock:` models.
    """
    from agent_arena.core.runner import ArenaRunner

    ArenaRunner.from_project(project_dir).run()

@pytest.fixture()
def sandbox(tmp_path: Path) -> Path:
    """A projects folder with one real project and one run, plus a canary."""
    root = tmp_path / "projects"
    root.mkdir()
    shutil.copytree(EXAMPLE, root / "support_triage",
                    ignore=shutil.ignore_patterns("results"))
    (tmp_path / "CANARY.txt").write_text("must survive", encoding="utf-8")
    _seed_run(root / "support_triage")
    return root


# ----------------------------------------------------------------- traversal


@pytest.mark.parametrize(
    "name", ["../CANARY.txt", "../..", "/etc/passwd", "a/b", "..", "", "  "]
)
def test_a_traversing_project_name_is_refused(sandbox, name):
    with pytest.raises(ServiceError):
        projects.delete_project(sandbox, name)
    assert (sandbox.parent / "CANARY.txt").exists()


def test_a_traversing_name_cannot_reach_outside_even_via_a_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "projects"
    root.mkdir()
    (root / "escape").symlink_to(outside)
    with pytest.raises(ServiceError):
        resolve_within(root, "escape/../../outside", "project name")


def test_safe_name_accepts_ordinary_names():
    for name in ("support_triage", "my-project", "run_20260903_175823_38dd9f"):
        assert safe_name(name) == name


# -------------------------------------------------------------------- dry run


def test_dry_run_returns_the_plan_and_changes_nothing(sandbox):
    before = sorted(p.name for p in (sandbox / "support_triage").iterdir())
    plan = projects.delete_project(sandbox, "support_triage", dry_run=True)

    assert plan["deleted"] is False
    assert plan["paths"]
    assert plan["bytes"] > 0
    assert sorted(p.name for p in (sandbox / "support_triage").iterdir()) == before


def test_the_dry_run_plan_matches_what_the_real_call_removes(sandbox):
    plan = projects.delete_project(sandbox, "support_triage", dry_run=True)
    done = projects.delete_project(sandbox, "support_triage")
    assert done["paths"] == plan["paths"]
    assert done["deleted"] is True
    assert not (sandbox / "support_triage").exists()


# --------------------------------------------------------------- keep results


def test_keep_results_leaves_the_history_behind(sandbox):
    projects.delete_project(sandbox, "support_triage", keep_results=True)
    remaining = sorted(p.name for p in (sandbox / "support_triage").iterdir())
    assert remaining == ["results"]


# ----------------------------------------------------------------- duplicate


def test_duplicate_excludes_results_so_history_is_not_misattributed(sandbox):
    detail = projects.duplicate_project(sandbox, "support_triage", "copy_one")
    copied = {p.name for p in (sandbox / "copy_one").iterdir()}
    assert "results" not in copied
    assert detail["runs"] == 0


def test_duplicate_rewrites_the_project_name(sandbox):
    detail = projects.duplicate_project(sandbox, "support_triage", "copy_one")
    assert detail["project"] == "copy_one"


def test_duplicating_onto_an_existing_name_is_refused(sandbox):
    projects.duplicate_project(sandbox, "support_triage", "copy_one")
    with pytest.raises(ServiceError):
        projects.duplicate_project(sandbox, "support_triage", "copy_one")


# ------------------------------------------------------------------- archive


def test_archiving_hides_a_project_from_the_default_listing(sandbox):
    projects.archive_project(sandbox, "support_triage")
    assert projects.list_projects(sandbox) == []
    assert len(projects.list_projects(sandbox, include_archived=True)) == 1


def test_archiving_is_reversible(sandbox):
    projects.archive_project(sandbox, "support_triage")
    projects.archive_project(sandbox, "support_triage", archived=False)
    assert len(projects.list_projects(sandbox)) == 1


# --------------------------------------------------------------- soft delete


def _a_run_id(sandbox) -> str:
    rows = runs.list_runs(sandbox, "support_triage", limit=1)
    assert rows, "the sandbox fixture should have produced a run"
    return rows[0]["run_id"]


def test_a_soft_deleted_run_disappears_from_every_read_path(sandbox):
    run_id = _a_run_id(sandbox)
    runs.delete_run(sandbox, "support_triage", run_id)

    config_db = sandbox / "support_triage" / "results" / "arena.sqlite"
    with ResultStore(config_db) as store:
        assert run_id not in [r["run_id"] for r in store.runs(limit=100)]
        assert store.run(run_id) is None
        assert store.rankings(run_id) == []
        assert store.results(run_id=run_id) == []
        row = next(iter(store.runs(limit=1, include_deleted=True)), None)
        assert row is not None  # still there, just hidden


def test_include_deleted_surfaces_it_again(sandbox):
    run_id = _a_run_id(sandbox)
    runs.delete_run(sandbox, "support_triage", run_id)
    visible = runs.list_runs(sandbox, "support_triage", limit=100, include_deleted=True)
    assert run_id in [r["run_id"] for r in visible]


def test_a_soft_delete_can_be_undone(sandbox):
    run_id = _a_run_id(sandbox)
    runs.delete_run(sandbox, "support_triage", run_id)
    runs.restore_run(sandbox, "support_triage", run_id)
    assert run_id in [r["run_id"] for r in runs.list_runs(sandbox, "support_triage", limit=100)]


def test_a_hard_delete_leaves_no_orphan_rows(sandbox):
    run_id = _a_run_id(sandbox)
    db = sandbox / "support_triage" / "results" / "arena.sqlite"
    runs.delete_run(sandbox, "support_triage", run_id, hard=True)
    with ResultStore(db) as store:
        orphans = store._conn.execute(  # noqa: SLF001 — asserting on storage
            "SELECT COUNT(*) FROM results WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        rankings = store._conn.execute(  # noqa: SLF001
            "SELECT COUNT(*) FROM rankings WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
    assert orphans == 0 and rankings == 0


def test_deleting_a_run_that_does_not_exist_says_so(sandbox):
    with pytest.raises(NotFoundError):
        runs.delete_run(sandbox, "support_triage", "run_does_not_exist")


def test_a_traversing_run_id_is_refused(sandbox):
    with pytest.raises(ServiceError):
        runs.delete_run(sandbox, "support_triage", "../../CANARY.txt")
    assert (sandbox.parent / "CANARY.txt").exists()


# ------------------------------------------------------------------- labels


def test_a_run_can_be_given_a_human_name(sandbox):
    run_id = _a_run_id(sandbox)
    runs.label_run(sandbox, "support_triage", run_id, label="before prompt change")
    row = runs.get_run(sandbox, "support_triage", run_id)
    assert row["label"] == "before prompt change"


def test_labelling_with_nothing_to_set_is_refused(sandbox):
    with pytest.raises(ServiceError):
        runs.label_run(sandbox, "support_triage", _a_run_id(sandbox))


# ------------------------------------------------------------------- vacuum


def test_vacuum_removes_only_soft_deleted_runs(sandbox):
    _seed_run(sandbox / "support_triage")  # a second run to keep
    all_runs = runs.list_runs(sandbox, "support_triage", limit=100)
    assert len(all_runs) >= 2
    doomed = all_runs[0]["run_id"]
    kept = all_runs[1]["run_id"]

    runs.delete_run(sandbox, "support_triage", doomed)
    plan = runs.vacuum(sandbox, "support_triage", dry_run=True)
    assert plan["runs_removed"] == 1
    assert runs.list_runs(sandbox, "support_triage", limit=100, include_deleted=True)

    runs.vacuum(sandbox, "support_triage")
    remaining = [
        r["run_id"]
        for r in runs.list_runs(sandbox, "support_triage", limit=100, include_deleted=True)
    ]
    assert doomed not in remaining
    assert kept in remaining


def test_vacuum_with_nothing_deleted_is_a_no_op(sandbox):
    plan = runs.vacuum(sandbox, "support_triage")
    assert plan["runs_removed"] == 0
