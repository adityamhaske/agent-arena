"""The results database."""

from __future__ import annotations

from pathlib import Path

from agent_arena.core.metrics import Leaderboard, ModelScore
from agent_arena.core.runner import CallResult
from agent_arena.core.store import ResultStore


def sample(model_key: str = "m", test_id: str = "t", **kwargs) -> CallResult:
    defaults = dict(
        model="mock:oracle",
        provider="mock",
        eval_type="exact_match",
        status="ok",
        score=1.0,
        passed=True,
        output="hello",
        reference="hello",
        latency_ms=12.5,
        input_tokens=3,
        output_tokens=2,
        cost_usd=0.0001,
        tags=["smoke"],
    )
    defaults.update(kwargs)
    return CallResult(model_key=model_key, test_id=test_id, **defaults)


def test_run_lifecycle(tmp_path: Path) -> None:
    with ResultStore(tmp_path / "arena.sqlite") as store:
        run_id = store.start_run(
            "proj", models=["m"], n_tests=1, weights={"accuracy": 1.0}
        )
        store.record_result(run_id, "proj", sample())

        board = Leaderboard(
            entries=[ModelScore(key="m", model="mock:oracle", rank=1, composite=0.9)]
        )
        store.finish_run(run_id, "proj", board, n_results=1, total_cost_usd=0.0001)

        run = store.runs("proj")[0]
        assert run["status"] == "completed"
        assert run["winner"] == "m"
        assert run["n_results"] == 1

        assert store.rankings(run_id)[0]["composite"] == 0.9


def test_results_can_be_filtered(tmp_path: Path) -> None:
    with ResultStore(tmp_path / "arena.sqlite") as store:
        run_id = store.start_run("proj", models=["a", "b"], n_tests=2, weights={})
        store.record_results(
            run_id,
            "proj",
            [sample("a", "t1"), sample("a", "t2"), sample("b", "t1")],
        )

        assert len(store.results(run_id=run_id)) == 3
        assert len(store.results(run_id=run_id, model_key="a")) == 2
        assert len(store.results(run_id=run_id, test_id="t1")) == 2


def test_reopening_an_existing_database_is_safe(tmp_path: Path) -> None:
    path = tmp_path / "arena.sqlite"
    with ResultStore(path) as store:
        run_id = store.start_run("proj", models=["m"], n_tests=1, weights={})
        store.record_result(run_id, "proj", sample())

    with ResultStore(path) as store:
        second = store.start_run("proj", models=["m"], n_tests=1, weights={})
        store.record_result(second, "proj", sample())

        assert len(store.runs("proj")) == 2
        assert len(store.results()) == 2


def test_oversized_output_is_truncated_not_rejected(tmp_path: Path) -> None:
    with ResultStore(tmp_path / "arena.sqlite") as store:
        run_id = store.start_run("proj", models=["m"], n_tests=1, weights={})
        store.record_result(run_id, "proj", sample(output="x" * 50_000))

        stored = store.results(run_id=run_id)[0]["output"]
        assert "truncated" in stored
        assert len(stored) < 50_000


def test_csv_export_round_trips(tmp_path: Path) -> None:
    with ResultStore(tmp_path / "arena.sqlite") as store:
        run_id = store.start_run("proj", models=["m"], n_tests=1, weights={})
        store.record_results(run_id, "proj", [sample("m", "t1"), sample("m", "t2")])

        path = store.export_csv(run_id, tmp_path / "out" / "results.csv")
        lines = path.read_text(encoding="utf-8").strip().splitlines()

        assert len(lines) == 3          # header + two rows
        assert "model_key" in lines[0]


def test_error_rows_keep_their_message(tmp_path: Path) -> None:
    with ResultStore(tmp_path / "arena.sqlite") as store:
        run_id = store.start_run("proj", models=["m"], n_tests=1, weights={})
        store.record_result(
            run_id, "proj", sample(status="error", score=None, passed=None, error="rate limited")
        )

        row = store.results(run_id=run_id)[0]
        assert row["status"] == "error"
        assert row["score"] is None
        assert row["error"] == "rate limited"
