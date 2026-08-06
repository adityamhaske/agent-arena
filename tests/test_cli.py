"""The `arena` command line."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_arena.cli import main

from .conftest import EXAMPLE_PROJECTS, write_project


def test_version(capsys) -> None:
    assert main(["--version"]) == 0
    assert "agent-arena" in capsys.readouterr().out


def test_no_command_prints_help(capsys) -> None:
    assert main([]) == 1
    assert "usage" in capsys.readouterr().out.lower()


def test_validate_reports_a_healthy_project(simple_project: Path, capsys) -> None:
    assert main(["validate", "--project", str(simple_project)]) == 0
    out = capsys.readouterr().out

    assert "✓ config" in out
    assert "valid and ready" in out


def test_validate_surfaces_a_config_error(tmp_path: Path, capsys) -> None:
    project = write_project(
        tmp_path / "broken",
        {"project": "broken", "models": []},
        [{"id": "a", "input": "q", "reference": "a"}],
    )
    assert main(["validate", "--project", str(project)]) == 1
    assert "at least one model" in capsys.readouterr().err


def test_tests_lists_the_cases(simple_project: Path, capsys) -> None:
    assert main(["tests", "--project", str(simple_project)]) == 0
    out = capsys.readouterr().out

    assert "4 test case(s)" in out
    assert "t1" in out


def test_dry_run_estimates_without_calling(simple_project: Path, capsys) -> None:
    assert main(["evaluate", "--project", str(simple_project), "--dry-run"]) == 0
    out = capsys.readouterr().out

    assert "dry run — nothing was called" in out
    assert "est. cost" in out


def test_evaluate_prints_a_leaderboard(simple_project: Path, capsys) -> None:
    assert main(["evaluate", "--project", str(simple_project), "--quiet"]) == 0
    out = capsys.readouterr().out

    assert "composite" in out
    assert "Winner: perfect" in out


def test_evaluate_json_output_is_machine_readable(simple_project: Path, capsys) -> None:
    assert main(["evaluate", "--project", str(simple_project), "--quiet", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["project"] == "simple"
    assert payload["leaderboard"]["winner"] == "perfect"
    assert len(payload["results"]) == 8


def test_fail_under_gates_ci(simple_project: Path, capsys) -> None:
    args = ["evaluate", "--project", str(simple_project), "--quiet", "--no-report"]

    assert main([*args, "--fail-under", "0.5"]) == 0
    assert main([*args, "--fail-under", "1.5"]) == 2
    assert "FAIL" in capsys.readouterr().err


def test_evaluate_honours_model_and_tag_filters(simple_project: Path, capsys) -> None:
    code = main(
        ["evaluate", "--project", str(simple_project), "--models", "perfect",
         "--ids", "t1", "--quiet", "--no-report"]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "perfect" in out
    assert "half" not in out.split("Winner")[0].replace("Small/fast", "")


def test_report_reads_back_a_stored_run(simple_project: Path, capsys) -> None:
    main(["evaluate", "--project", str(simple_project), "--quiet", "--no-report"])
    capsys.readouterr()

    assert main(["report", "--project", str(simple_project)]) == 0
    out = capsys.readouterr().out
    assert "perfect" in out
    assert "composite" in out


def test_report_without_any_runs_says_so(simple_project: Path, capsys) -> None:
    assert main(["report", "--project", str(simple_project)]) == 1
    assert "No runs recorded" in capsys.readouterr().out


def test_history_lists_runs(simple_project: Path, capsys) -> None:
    main(["evaluate", "--project", str(simple_project), "--quiet", "--no-report"])
    capsys.readouterr()

    assert main(["history", "--project", str(simple_project)]) == 0
    assert "recent runs" in capsys.readouterr().out


def test_history_for_one_model(simple_project: Path, capsys) -> None:
    main(["evaluate", "--project", str(simple_project), "--quiet", "--no-report"])
    capsys.readouterr()

    assert main(["history", "--project", str(simple_project), "--model", "perfect"]) == 0
    assert "over time" in capsys.readouterr().out


def test_models_command_flags_unpriced_models(tmp_path: Path, capsys) -> None:
    project = write_project(
        tmp_path / "unpriced",
        {"project": "unpriced", "models": ["some-unknown-model"]},
        [{"id": "a", "input": "q", "reference": "a"}],
    )
    assert main(["models", "--project", str(project)]) == 0
    out = capsys.readouterr().out

    assert "No pricing for" in out
    assert "rather than guessed" in out


def test_models_command_without_a_project_lists_the_catalog(capsys) -> None:
    assert main(["models"]) == 0
    out = capsys.readouterr().out

    assert "claude-opus-5" in out
    assert "Verify against your provider" in out


def test_scorers_command_lists_eval_types(capsys) -> None:
    assert main(["scorers"]) == 0
    out = capsys.readouterr().out

    assert "exact_match" in out
    assert "llm_judge" in out


def test_scorers_command_includes_project_local_ones(capsys) -> None:
    project = EXAMPLE_PROJECTS / "doc_extraction"
    assert main(["scorers", "--project", str(project)]) == 0
    assert "iso_currency" in capsys.readouterr().out


def test_init_scaffolds_a_runnable_project(tmp_path: Path, capsys) -> None:
    target = tmp_path / "fresh"
    assert main(["init", str(target), "--name", "fresh"]) == 0

    assert (target / "config.yaml").is_file()
    assert (target / "tests.yaml").is_file()
    assert "project: fresh" in (target / "config.yaml").read_text(encoding="utf-8")
    assert "Next:" in capsys.readouterr().out


def test_init_refuses_to_overwrite_by_default(tmp_path: Path, capsys) -> None:
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "keep.txt").write_text("mine", encoding="utf-8")

    assert main(["init", str(target)]) == 1
    assert "not empty" in capsys.readouterr().err


@pytest.mark.parametrize("project", ["support_triage", "doc_extraction"])
def test_bundled_example_projects_are_valid(project: str, capsys) -> None:
    """The shipped examples must stay runnable — they are the documentation."""
    assert main(["validate", "--project", str(EXAMPLE_PROJECTS / project)]) == 0
    assert "valid and ready" in capsys.readouterr().out
