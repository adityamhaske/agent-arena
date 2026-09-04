"""Tests for the lifecycle commands: projects, runs, rm, export, providers,
secrets, config, env.

These commands were added across several sessions and, until now, none of them
had a test that actually invoked `main()` — the service layer underneath each
was well covered, but the argument parsing, the confirmation prompts, and the
printed output were not. A wiring mistake here (a wrong flag name, a missing
`--yes` check) would have shipped silently.

`arena secrets` and `arena providers` touch the OS keyring by default; every
test that reaches them disables it via `_store_tool`, the same way
tests/test_service_providers.py does, so this suite never writes into the
developer's real Keychain.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_arena.cli import main
from agent_arena.core.runner import ArenaRunner

from .conftest import write_project


@pytest.fixture(autouse=True)
def isolated_config(tmp_path_factory, monkeypatch):
    """Never touch the developer's real settings or OS keychain."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("config")))
    monkeypatch.setattr("agent_arena.core.secrets._store_tool", lambda: None)


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A project folder under its own projects/ directory, with one run."""
    root = write_project(
        tmp_path / "projects" / "demo",
        {
            "project": "demo",
            "models": [{"key": "m", "model": "mock:oracle"}],
            "scorers": {"default": "exact_match"},
        },
        [{"id": "t1", "input": "hello", "reference": "hello"}],
    )
    ArenaRunner.from_project(root).run()
    return root


def _run_id(project: Path) -> str:
    from agent_arena.service.runs import list_runs

    rows = list_runs(project.parent, project.name, limit=1)
    assert rows, "the project fixture should have produced a run"
    return rows[0]["run_id"]


# ------------------------------------------------------------------ projects


def test_projects_lists_a_project(project: Path, capsys):
    assert main(["projects", "--projects-dir", str(project.parent)]) == 0
    assert "demo" in capsys.readouterr().out


def test_projects_on_an_empty_directory_says_so_and_how_to_start(tmp_path, capsys):
    empty = tmp_path / "projects"
    empty.mkdir()
    assert main(["projects", "--projects-dir", str(empty)]) == 0
    out = capsys.readouterr().out
    assert "No projects" in out and "arena init" in out


def test_archiving_hides_a_project_and_undo_restores_it(project: Path, capsys):
    assert main(["archive", "project", "demo", "--projects-dir", str(project.parent)]) == 0
    capsys.readouterr()
    main(["projects", "--projects-dir", str(project.parent)])
    assert "demo" not in capsys.readouterr().out

    main(["archive", "project", "demo", "--projects-dir", str(project.parent), "--undo"])
    capsys.readouterr()
    main(["projects", "--projects-dir", str(project.parent)])
    assert "demo" in capsys.readouterr().out


def test_duplicate_copies_a_project_without_its_results(project: Path, capsys):
    assert main(["duplicate", "demo", "demo_copy", "--projects-dir", str(project.parent)]) == 0
    copy = project.parent / "demo_copy"
    assert copy.is_dir()
    assert "results" not in {p.name for p in copy.iterdir()}
    assert "demo_copy" in capsys.readouterr().out


# ----------------------------------------------------------------------- runs


def test_runs_lists_a_seeded_run(project: Path, capsys):
    assert main(["runs", "--project", str(project)]) == 0
    assert _run_id(project) in capsys.readouterr().out


def test_label_sets_a_human_name_visible_in_the_listing(project: Path, capsys):
    run_id = _run_id(project)
    assert main(["label", "--project", str(project), run_id, "--label", "before change"]) == 0
    capsys.readouterr()
    main(["runs", "--project", str(project)])
    assert "before change" in capsys.readouterr().out


# ------------------------------------------------------------------------- rm


def test_rm_run_dry_run_prints_the_plan_and_changes_nothing(project: Path, capsys):
    run_id = _run_id(project)
    assert main(["rm", "run", run_id, "--project", str(project), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "This will remove" in out and "dry run" in out
    assert run_id in [r for r in [_run_id(project)]]  # still there


def test_rm_run_without_a_tty_and_without_yes_refuses(project: Path, capsys):
    run_id = _run_id(project)
    assert main(["rm", "run", run_id, "--project", str(project)]) == 1
    assert "refusing" in capsys.readouterr().err.lower()
    assert _run_id(project) == run_id  # untouched


def test_rm_run_with_yes_soft_deletes_it(project: Path, capsys):
    run_id = _run_id(project)
    assert main(["rm", "run", run_id, "--project", str(project), "--yes"]) == 0
    assert "Deleted" in capsys.readouterr().out
    from agent_arena.service.runs import list_runs

    assert list_runs(project.parent, project.name) == []
    assert len(list_runs(project.parent, project.name, include_deleted=True)) == 1


def test_rm_project_dry_run_leaves_the_folder_in_place(project: Path, capsys):
    assert main(["rm", "project", "demo", "--projects-dir", str(project.parent), "--dry-run"]) == 0
    assert project.is_dir()


def test_rm_project_with_yes_removes_the_folder(project: Path, capsys):
    assert main(["rm", "project", "demo", "--projects-dir", str(project.parent), "--yes"]) == 0
    assert not project.is_dir()


def test_rm_project_keep_results_leaves_the_database(project: Path, capsys):
    main(["rm", "project", "demo", "--projects-dir", str(project.parent), "--keep-results", "--yes"])
    assert {p.name for p in project.iterdir()} == {"results"}


# --------------------------------------------------------------------- vacuum


def test_vacuum_with_nothing_deleted_says_so(project: Path, capsys):
    assert main(["vacuum", "--project", str(project)]) == 0
    assert "Nothing to reclaim" in capsys.readouterr().out


def test_vacuum_removes_a_soft_deleted_run(project: Path, capsys):
    run_id = _run_id(project)
    main(["rm", "run", run_id, "--project", str(project), "--yes"])
    capsys.readouterr()
    assert main(["vacuum", "--project", str(project), "--yes"]) == 0
    assert "Removed 1 run" in capsys.readouterr().out


# --------------------------------------------------------------------- export


def test_export_writes_a_file_and_says_so(project: Path, tmp_path: Path, capsys):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    assert main(["export", "--project", str(project), "--format", "json", "--out", str(out_dir)]) == 0
    written = list(out_dir.glob("*.json"))
    assert written and "Wrote" in capsys.readouterr().out


def test_export_all_produces_one_document_for_every_run(project: Path, tmp_path: Path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    assert main(["export", "--project", str(project), "--all", "--out", str(out_dir)]) == 0
    files = list(out_dir.glob("*-export.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text())
    assert payload["schema_version"] == 1


def test_an_unknown_export_format_is_rejected(project: Path, capsys):
    with pytest.raises(SystemExit):
        main(["export", "--project", str(project), "--format", "yaml"])


# ------------------------------------------------------------------------ env


def test_env_with_no_files_says_so(project: Path, capsys):
    assert main(["env", "--project", str(project)]) == 0
    assert "No .env files found" in capsys.readouterr().out


def test_env_never_prints_a_value(project: Path, capsys):
    (project / ".env").write_text("SECRET=sk-do-not-print-me\n", encoding="utf-8")
    assert main(["env", "--project", str(project)]) == 0
    out = capsys.readouterr().out
    assert "sk-do-not-print-me" not in out
    assert ".env" in out


# ------------------------------------------------------------------ providers


def test_providers_add_then_list(capsys):
    assert main(["providers", "add", "work", "--kind", "openai",
                 "--api-key", "${env:OPENAI_API_KEY}"]) == 0
    capsys.readouterr()
    main(["providers", "list"])
    assert "work" in capsys.readouterr().out


def test_providers_add_with_a_literal_key_never_prints_it(capsys):
    assert main(["providers", "add", "gw", "--kind", "openai",
                 "--api-key", "sk-typed-into-the-cli"]) == 0
    out = capsys.readouterr().out
    assert "sk-typed-into-the-cli" not in out
    assert "keyring" in out


def test_providers_rm_without_yes_and_no_tty_refuses(capsys):
    main(["providers", "add", "gw", "--kind", "openai"])
    capsys.readouterr()
    assert main(["providers", "rm", "gw"]) == 1
    assert "Cancelled" in capsys.readouterr().out


def test_providers_rm_with_yes_deletes_it(capsys):
    main(["providers", "add", "gw", "--kind", "openai"])
    capsys.readouterr()
    assert main(["providers", "rm", "gw", "--yes"]) == 0
    capsys.readouterr()
    main(["providers", "list"])
    assert "gw" not in capsys.readouterr().out


def test_providers_with_a_malformed_header_is_rejected(capsys):
    assert main(["providers", "add", "gw", "--kind", "openai", "--header", "not-a-pair"]) == 1
    assert "KEY=VALUE" in capsys.readouterr().err


# -------------------------------------------------------------------- secrets


def test_secrets_round_trip_masked_by_default(capsys):
    assert main(["secrets", "set", "acct", "--value", "sk-real-value"]) == 0
    capsys.readouterr()
    main(["secrets", "get", "acct"])
    assert capsys.readouterr().out.strip() == "***"


def test_secrets_get_reveal_shows_the_real_value(capsys):
    main(["secrets", "set", "acct", "--value", "sk-real-value"])
    capsys.readouterr()
    main(["secrets", "get", "acct", "--reveal"])
    assert capsys.readouterr().out.strip() == "sk-real-value"


def test_secrets_rm_removes_it(capsys):
    main(["secrets", "set", "acct", "--value", "x"])
    capsys.readouterr()
    assert main(["secrets", "rm", "acct"]) == 0
    assert main(["secrets", "get", "acct"]) == 1


def test_secrets_get_on_nothing_stored_fails_clearly(capsys):
    assert main(["secrets", "get", "never-set"]) == 1
    assert "No credential" in capsys.readouterr().err


# --------------------------------------------------------------------- config


def test_config_get_returns_json_without_provider_secrets(capsys):
    assert main(["config", "get"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "theme" in payload
    assert "providers" not in payload  # shown by `arena providers list` instead


def test_config_set_then_get_round_trips(capsys):
    assert main(["config", "set", "theme", "dark"]) == 0
    capsys.readouterr()
    from agent_arena.service.settings import load

    assert load()["theme"] == "dark"


def test_config_reset_restores_the_default(capsys):
    main(["config", "set", "theme", "dark"])
    capsys.readouterr()
    assert main(["config", "reset", "theme"]) == 0
    from agent_arena.service.settings import load, DEFAULTS

    assert load()["theme"] == DEFAULTS["theme"]
