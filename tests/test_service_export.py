"""Tests for getting data out.

The HTML format carries the weight here, because it is the one that leaves the
machine: someone emails it to the person who owns the budget. Two properties
have to hold or that is a bad idea — it must render with no network, and it must
not execute anything a model wrote. Model output is untrusted text full of angle
brackets, and an evaluation report that ran its own contents would be a
genuinely bad look.

The redaction test exists because every run stores the config it ran under,
which is exactly where a literal credential hides if someone pasted one instead
of using a reference.
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from agent_arena.core.store import ResultStore
from agent_arena.service import export
from agent_arena.service.errors import NotFoundError, ServiceError

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
    root = tmp_path / "projects"
    root.mkdir()
    shutil.copytree(EXAMPLE, root / "support_triage",
                    ignore=shutil.ignore_patterns("results"))
    _seed_run(root / "support_triage")
    return root


@pytest.mark.parametrize("fmt", ["csv", "json", "markdown", "html"])
def test_every_format_writes_a_file(sandbox, tmp_path, fmt):
    path = export.export_run(sandbox, "support_triage", None, fmt, tmp_path / "out")
    assert path.exists() and path.stat().st_size > 0


def test_a_directory_destination_generates_a_filename(sandbox, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    path = export.export_run(sandbox, "support_triage", None, "json", out)
    assert path.parent == out


def test_an_explicit_file_destination_is_used_as_given(sandbox, tmp_path):
    target = tmp_path / "report.json"
    path = export.export_run(sandbox, "support_triage", None, "json", target)
    assert path == target


def test_an_unknown_format_lists_the_ones_that_work(sandbox, tmp_path):
    with pytest.raises(ServiceError) as exc:
        export.export_run(sandbox, "support_triage", None, "pdf", tmp_path)
    assert "csv" in str(exc.value) and "html" in str(exc.value)


def test_a_missing_run_says_so(sandbox, tmp_path):
    with pytest.raises(NotFoundError):
        export.export_run(sandbox, "support_triage", "run_nope", "json", tmp_path)


def test_a_traversing_run_id_is_refused(sandbox, tmp_path):
    with pytest.raises(ServiceError):
        export.export_run(sandbox, "support_triage", "../../etc", "json", tmp_path)


# ---------------------------------------------------------------------- html


def test_the_html_export_needs_no_network(sandbox, tmp_path):
    path = export.export_run(sandbox, "support_triage", None, "html", tmp_path)
    body = path.read_text(encoding="utf-8")
    assert "http://" not in body
    assert "https://" not in body


def test_the_html_export_runs_no_script(sandbox, tmp_path):
    path = export.export_run(sandbox, "support_triage", None, "html", tmp_path)
    assert "<script" not in path.read_text(encoding="utf-8").lower()


def test_the_html_export_escapes_model_output(sandbox, tmp_path):
    """A model that returns markup must not become markup in the report."""
    config_db = sandbox / "support_triage" / "results" / "arena.sqlite"
    with ResultStore(config_db) as store:
        run_id = store.runs(limit=1)[0]["run_id"]
        store._conn.execute(  # noqa: SLF001 — planting a hostile row on purpose
            "UPDATE results SET output = ? WHERE run_id = ? AND id = "
            "(SELECT MIN(id) FROM results WHERE run_id = ?)",
            ("<script>alert(1)</script>", run_id, run_id),
        )
        store._conn.commit()  # noqa: SLF001

    path = export.export_run(sandbox, "support_triage", run_id, "html", tmp_path)
    body = path.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_the_html_export_handles_both_colour_schemes(sandbox, tmp_path):
    path = export.export_run(sandbox, "support_triage", None, "html", tmp_path)
    assert "prefers-color-scheme" in path.read_text(encoding="utf-8")


# ----------------------------------------------------------------------- csv


def test_the_csv_round_trips(sandbox, tmp_path):
    path = export.export_run(sandbox, "support_triage", None, "csv", tmp_path)
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    for column in ("run_id", "model_key", "test_id", "score", "status"):
        assert column in rows[0]


# ---------------------------------------------------------------------- json


def test_the_json_export_carries_a_schema_version(sandbox, tmp_path):
    path = export.export_run(sandbox, "support_triage", None, "json", tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["run"] and payload["rankings"]


def test_export_all_includes_every_run(sandbox, tmp_path):
    path = export.export_all(sandbox, "support_triage", tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert len(payload["runs"]) >= 1


# ----------------------------------------------------------------- redaction


def test_a_credential_in_a_stored_config_is_not_exported(sandbox, tmp_path):
    config_db = sandbox / "support_triage" / "results" / "arena.sqlite"
    with ResultStore(config_db) as store:
        run_id = store.runs(limit=1)[0]["run_id"]
        store._conn.execute(  # noqa: SLF001
            "UPDATE runs SET config_json = ? WHERE run_id = ?",
            (json.dumps({"providers": [{"id": "p", "api_key": "sk-ant-leaked-value"}]}), run_id),
        )
        store._conn.commit()  # noqa: SLF001

    for fmt in ("json", "html", "markdown"):
        path = export.export_run(sandbox, "support_triage", run_id, fmt, tmp_path / fmt)
        assert "sk-ant-leaked-value" not in path.read_text(encoding="utf-8")


def test_a_reference_survives_redaction_because_it_is_not_a_secret(sandbox, tmp_path):
    config_db = sandbox / "support_triage" / "results" / "arena.sqlite"
    with ResultStore(config_db) as store:
        run_id = store.runs(limit=1)[0]["run_id"]
        store._conn.execute(  # noqa: SLF001
            "UPDATE runs SET config_json = ? WHERE run_id = ?",
            (json.dumps({"providers": [{"id": "p", "api_key": "${env:OPENAI_API_KEY}"}]}), run_id),
        )
        store._conn.commit()  # noqa: SLF001

    path = export.export_run(sandbox, "support_triage", run_id, "json", tmp_path)
    assert "${env:OPENAI_API_KEY}" in path.read_text(encoding="utf-8")
