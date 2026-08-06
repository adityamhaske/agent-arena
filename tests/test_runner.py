"""End-to-end runs, entirely offline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_arena import run
from agent_arena.core.config import ProjectConfig
from agent_arena.core.errors import ConfigError
from agent_arena.core.report import Report, write_reports
from agent_arena.core.runner import ArenaRunner
from agent_arena.core.store import ResultStore

from .conftest import write_project


def test_full_run_produces_a_ranked_leaderboard(simple_project: Path) -> None:
    result = run(simple_project)

    assert len(result.results) == 8          # 2 models × 4 tests × 1 trial
    assert result.error_count == 0
    assert result.winner.key == "perfect"
    assert result.leaderboard.get("perfect").raw("accuracy") == 1.0
    assert result.leaderboard.get("half").raw("accuracy") < 1.0


def test_trials_multiply_the_call_count(simple_project: Path) -> None:
    result = run(simple_project, trials=3)
    assert len(result.results) == 24


def test_overrides_narrow_the_run(simple_project: Path) -> None:
    result = run(simple_project, models=["perfect"], limit=2)

    assert {r.model_key for r in result.results} == {"perfect"}
    assert len(result.test_cases) == 2


def test_results_are_persisted_and_queryable(simple_project: Path) -> None:
    result = run(simple_project)
    config = ProjectConfig.load(simple_project)

    with ResultStore(config.database) as store:
        runs = store.runs(project="simple")
        assert runs[0]["run_id"] == result.run_id
        assert runs[0]["status"] == "completed"
        assert runs[0]["n_results"] == 8

        rows = store.results(run_id=result.run_id)
        assert len(rows) == 8
        assert {row["model_key"] for row in rows} == {"perfect", "half"}

        rankings = store.rankings(result.run_id)
        assert rankings[0]["model_key"] == "perfect"
        assert rankings[0]["rank"] == 1


def test_history_tracks_a_model_across_runs(simple_project: Path) -> None:
    run(simple_project)
    run(simple_project)
    config = ProjectConfig.load(simple_project)

    with ResultStore(config.database) as store:
        history = store.model_history("simple", "perfect")
        assert len(history) == 2
        assert all(row["accuracy"] == 1.0 for row in history)


def test_flaky_tests_are_detectable(simple_project: Path) -> None:
    """The coin-flip model is deterministic per (test, trial), so varying the
    trial number is what exposes instability."""
    run(simple_project, trials=4)
    config = ProjectConfig.load(simple_project)

    with ResultStore(config.database) as store:
        flaky = store.flaky_tests("simple")
        assert all(row["model_key"] == "half" for row in flaky)


def test_dry_run_calls_nothing(simple_project: Path) -> None:
    runner = ArenaRunner.from_project(simple_project)
    result = runner.run(dry_run=True)

    assert result.results == []
    assert result.run_id == "dry-run"


def test_reports_are_written_in_the_requested_formats(tmp_path: Path) -> None:
    project = write_project(
        tmp_path / "rep",
        {
            "project": "rep",
            "models": [{"key": "m", "model": "mock:oracle"}],
            "output": {"dir": "results", "formats": ["markdown", "json", "csv"]},
        },
        [{"id": "a", "input": "q", "reference": "a"}],
    )
    result = run(project)
    written = write_reports(result)

    assert set(written) == {"markdown", "json", "csv"}
    assert written["markdown"].read_text(encoding="utf-8").startswith("# rep")
    assert json.loads(written["json"].read_text(encoding="utf-8"))["run_id"] == result.run_id
    assert "model_key" in written["csv"].read_text(encoding="utf-8")


def test_report_explains_the_tradeoff_not_just_the_winner(tmp_path: Path) -> None:
    project = write_project(
        tmp_path / "trade",
        {
            "project": "trade",
            "models": [
                {"key": "accurate_slow", "model": "mock:oracle", "params": {"latency_ms": 5000}},
                {
                    "key": "fast_wrong",
                    "model": "mock:fast",
                    "params": {"mode": "flaky", "accuracy": 50, "latency_ms": 10},
                },
            ],
            "metrics": {"weights": {"accuracy": 0.5, "latency": 0.5}},
            "output": {"formats": []},
        },
        [{"id": f"t{i}", "input": "q", "reference": "a"} for i in range(6)],
    )
    markdown = Report(run(project)).markdown()

    assert "## Recommendation" in markdown
    assert "while losing on" in markdown
    assert "## Per-test results" in markdown


# ---- preflight -------------------------------------------------------------


def test_preflight_rejects_an_unknown_eval_type(tmp_path: Path) -> None:
    project = write_project(
        tmp_path / "bad",
        {"project": "bad", "models": ["mock:oracle"]},
        [{"id": "a", "input": "q", "reference": "a", "eval_type": "does_not_exist"}],
    )
    with pytest.raises(Exception, match="unknown eval_type"):
        run(project)


def test_preflight_catches_a_missing_reference_before_spending(tmp_path: Path) -> None:
    project = write_project(
        tmp_path / "noref",
        {"project": "noref", "models": ["mock:oracle"]},
        [{"id": "a", "input": "q"}],
    )
    with pytest.raises(ConfigError, match="need a 'reference'"):
        run(project)


def test_preflight_requires_a_judge_for_llm_judge_cases(tmp_path: Path) -> None:
    project = write_project(
        tmp_path / "judge",
        {"project": "judge", "models": ["mock:oracle"]},
        [{"id": "a", "input": "q", "reference": "a", "eval_type": "llm_judge"}],
    )
    with pytest.raises(ConfigError, match="no judge is configured"):
        run(project)


def test_models_without_credentials_are_skipped_not_failed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    project = write_project(
        tmp_path / "skip",
        {
            "project": "skip",
            "models": [{"key": "local", "model": "mock:oracle"}, "claude-opus-5"],
            "output": {"formats": []},
        },
        [{"id": "a", "input": "q", "reference": "a"}],
    )
    result = run(project)

    assert "claude-opus-5" in result.skipped_models
    entry = result.leaderboard.get("claude-opus-5")
    assert entry.status == "no_data"
    # The skip is the whole story — "no results recorded" is its consequence,
    # not a second, separate problem to report.
    assert entry.failures == ["skipped — ANTHROPIC_API_KEY is not set"]
    assert result.winner.key == "local"          # the run still produces an answer


def test_a_priced_model_with_no_results_is_not_reported_as_unpriced(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    project = write_project(
        tmp_path / "priced",
        {
            "project": "priced",
            "models": [{"key": "local", "model": "mock:oracle"}, "claude-opus-5"],
            "metrics": {"weights": {"accuracy": 0.5, "cost": 0.5}},
            "output": {"formats": []},
        },
        [{"id": "a", "input": "q", "reference": "a"}],
    )
    notes = " ".join(run(project).leaderboard.notes)

    assert "claude-opus-5" not in notes      # it is in the catalog; it just did not run


def test_a_run_where_every_model_is_skipped_fails_loudly(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    project = write_project(
        tmp_path / "allskipped",
        {"project": "allskipped", "models": ["claude-opus-5"]},
        [{"id": "a", "input": "q", "reference": "a"}],
    )
    with pytest.raises(ConfigError, match="every model would be skipped"):
        run(project)


# ---- hooks and custom scorers ---------------------------------------------


HOOKS = '''
def post_process(output, test_case, context):
    return {"output": output.strip().upper(), "metrics": {"cleanups": 1.0}}
'''

VERDICT_HOOK = '''
def post_process(output, test_case, context):
    return {"output": output, "passed": False, "score": 0.0, "reason": "vetoed by hook"}
'''

CUSTOM_SCORER = '''
from agent_arena.scorers import Scorer, ScoreResult


class LengthScorer(Scorer):
    name = "short_enough"
    requires_reference = False

    def score(self, output, reference, context):
        ok = len(output) <= int(context.params.get("max_chars", 10))
        return ScoreResult(score=1.0 if ok else 0.0, passed=ok,
                           metrics={"chars": float(len(output))})
'''


def test_post_process_hook_rewrites_the_output(tmp_path: Path) -> None:
    project = write_project(
        tmp_path / "hooked",
        {
            "project": "hooked",
            "models": [{"key": "m", "model": "mock:oracle"}],
            "hooks": {"post_process": "hooks.py:post_process"},
            "output": {"formats": []},
        },
        [{"id": "a", "input": "q", "reference": "ALPHA"}],
        extra_files={"hooks.py": HOOKS},
    )
    result = run(project)

    assert result.results[0].output == "ALPHA"
    assert result.results[0].metrics["cleanups"] == 1.0
    assert result.results[0].passed is True


def test_post_process_hook_can_override_the_verdict(tmp_path: Path) -> None:
    project = write_project(
        tmp_path / "veto",
        {
            "project": "veto",
            "models": [{"key": "m", "model": "mock:oracle"}],
            "hooks": {"post_process": "hooks.py:post_process"},
            "output": {"formats": []},
        },
        [{"id": "a", "input": "q", "reference": "a"}],
        extra_files={"hooks.py": VERDICT_HOOK},
    )
    result = run(project)

    assert result.results[0].passed is False
    assert result.results[0].reason == "vetoed by hook"


def test_project_local_scorer_is_discovered_by_convention(tmp_path: Path) -> None:
    project = write_project(
        tmp_path / "custom",
        {
            "project": "custom",
            "models": [{"key": "m", "model": "mock:oracle"}],
            "scorers": {"default": "short_enough"},
            "metrics": {"weights": {"accuracy": 0.8, "chars": 0.2}},
            "output": {"formats": []},
        },
        [{"id": "a", "input": "q", "reference": "tiny"}],
        extra_files={"scorers/length.py": CUSTOM_SCORER},
    )
    result = run(project)

    assert result.results[0].passed is True
    # A custom metric can be weighted in the composite like any builtin.
    assert "chars" in result.leaderboard.get("m").metrics


def test_unknown_hook_name_is_rejected(tmp_path: Path) -> None:
    project = write_project(
        tmp_path / "badhook",
        {
            "project": "badhook",
            "models": ["mock:oracle"],
            "hooks": {"after_everything": "hooks.py:post_process"},
        },
        [{"id": "a", "input": "q", "reference": "a"}],
        extra_files={"hooks.py": HOOKS},
    )
    with pytest.raises(Exception, match="unknown hook"):
        run(project)


# ---- failure handling ------------------------------------------------------


EXPLODING_SCORER = '''
from agent_arena.scorers import Scorer, ScoreResult


class BoomScorer(Scorer):
    name = "boom"
    requires_reference = False

    def score(self, output, reference, context):
        raise RuntimeError("scorer exploded")
'''


def test_a_broken_scorer_fails_its_call_not_the_whole_run(tmp_path: Path) -> None:
    project = write_project(
        tmp_path / "boom",
        {
            "project": "boom",
            "models": [{"key": "m", "model": "mock:oracle"}],
            "scorers": {"default": "boom"},
            "output": {"formats": []},
        },
        [{"id": "a", "input": "q", "reference": "a"}, {"id": "b", "input": "q", "reference": "b"}],
        extra_files={"scorers/boom.py": EXPLODING_SCORER},
    )
    result = run(project)

    assert len(result.results) == 2
    assert all(r.status == "error" for r in result.results)
    assert "scorer exploded" in result.results[0].error
    assert result.leaderboard.get("m").status == "no_data"
