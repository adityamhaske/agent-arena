"""Tests for evaluating a pipeline instead of a single model call.

The contract worth protecting: a target is graded, ranked and disqualified by
exactly the same machinery as a model, and a pipeline that reports its own spend
is believed over the price catalog — because it is the only thing that knows
what its internal calls cost.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from agent_arena.connectors.base import GenerationRequest
from agent_arena.connectors.callable_target import CallableConnector
from agent_arena.connectors.registry import (
    build_connector,
    requires_api_key,
    resolve_provider,
)
from agent_arena.core.config import ModelSpec, ProjectConfig
from agent_arena.core.errors import ConfigError, ConnectorError
from agent_arena.core.runner import ArenaRunner
from tests.conftest import write_project

PIPELINE = '''
def plain(prompt):
    """Simplest possible target: prompt in, string out."""
    return "billing" if "charged" in prompt else "technical"


def with_context(prompt, test_id=None, tags=None):
    """Declares only the context it wants."""
    return f"{test_id}|{','.join(tags or [])}"


def greedy(prompt, **kwargs):
    """Takes everything."""
    return ",".join(sorted(kwargs))


def reports_usage(prompt):
    """A pipeline that knows its own end-to-end spend."""
    return {
        "output": "billing",
        "input_tokens": 1234,
        "output_tokens": 56,
        "cost_usd": 0.25,
        "latency_ms": 987.0,
        "metrics": {"agent_calls": 3.0, "retrieved_docs": 8.0},
    }


def no_output_key(prompt):
    return {"nope": 1}


def wrong_type(prompt):
    return 42


class Result:
    def __init__(self, text):
        self.text = text


def returns_object(prompt):
    return Result("billing")


def explodes(prompt):
    raise RuntimeError("pipeline blew up")
'''


@pytest.fixture()
def pipeline_dir(tmp_path: Path) -> Path:
    (tmp_path / "pipe.py").write_text(textwrap.dedent(PIPELINE), encoding="utf-8")
    return tmp_path


def _connector(pipeline_dir: Path, function: str) -> CallableConnector:
    return CallableConnector("target", run=f"pipe.py:{function}", base_dir=pipeline_dir)


def _request(prompt: str = "I was charged twice", **metadata) -> GenerationRequest:
    return GenerationRequest(
        messages=[{"role": "user", "content": prompt}], metadata=metadata
    )


class ConnectorTests:
    def test_a_plain_string_target_works(self, pipeline_dir):
        result = _connector(pipeline_dir, "plain").generate(_request())
        assert result.text == "billing"
        assert result.provider == "callable"
        assert result.latency_ms >= 0

    def test_a_target_receives_only_the_context_it_declares(self, pipeline_dir):
        result = _connector(pipeline_dir, "with_context").generate(
            _request(test_id="t1", tags=["a", "b"])
        )
        assert result.text == "t1|a,b"

    def test_a_target_taking_kwargs_receives_everything(self, pipeline_dir):
        result = _connector(pipeline_dir, "greedy").generate(_request(test_id="t1"))
        received = set(result.text.split(","))
        assert {"messages", "system", "test_id", "trial", "tags", "params", "reference"} == received

    def test_self_reported_usage_is_carried_through(self, pipeline_dir):
        result = _connector(pipeline_dir, "reports_usage").generate(_request())
        assert result.input_tokens == 1234
        assert result.output_tokens == 56
        assert result.cost_usd == 0.25
        assert result.latency_ms == 987.0
        assert result.metrics == {"agent_calls": 3.0, "retrieved_docs": 8.0}

    def test_tokens_are_estimated_only_when_not_reported(self, pipeline_dir):
        result = _connector(pipeline_dir, "plain").generate(_request())
        assert result.input_tokens > 0
        assert result.cost_usd is None  # never guessed

    def test_an_object_with_a_text_attribute_is_accepted(self, pipeline_dir):
        assert _connector(pipeline_dir, "returns_object").generate(_request()).text == "billing"

    @pytest.mark.parametrize("function", ["no_output_key", "wrong_type"])
    def test_an_unusable_return_says_what_to_return(self, pipeline_dir, function):
        with pytest.raises(ConnectorError, match="output"):
            _connector(pipeline_dir, function).generate(_request())

    def test_a_bad_run_spec_is_refused_at_construction(self, pipeline_dir):
        with pytest.raises(ConnectorError, match="path/to/file.py:function"):
            CallableConnector("target", run="pipe.py", base_dir=pipeline_dir)

    def test_healthcheck_catches_a_typo_before_the_run(self, pipeline_dir):
        assert _connector(pipeline_dir, "plain").healthcheck() is None
        assert "no attribute" in (_connector(pipeline_dir, "nosuchfn").healthcheck() or "")

    def test_a_relative_path_resolves_against_the_project_not_the_cwd(self, pipeline_dir):
        connector = CallableConnector("t", run="pipe.py:plain", base_dir=pipeline_dir)
        assert connector.generate(_request()).text == "billing"


class RoutingTests:
    def test_run_decides_the_provider(self):
        spec = ModelSpec(key="p", model="anything", run="pipe.py:plain")
        assert resolve_provider(spec) == "callable"

    def test_run_beats_a_model_id_that_would_route_elsewhere(self):
        """A target named after a real model must still run the callable."""
        spec = ModelSpec(key="p", model="claude-opus-5", run="pipe.py:plain")
        assert resolve_provider(spec) == "callable"

    def test_a_target_needs_no_api_key(self):
        spec = ModelSpec(key="p", model="claude-opus-5", run="pipe.py:plain")
        assert requires_api_key(spec) is None

    def test_build_connector_passes_the_run_spec_and_root(self, pipeline_dir):
        spec = ModelSpec(key="p", model="pipe.py:plain", run="pipe.py:plain")
        spec.base_dir = pipeline_dir
        connector = build_connector(spec)
        assert isinstance(connector, CallableConnector)
        assert connector.generate(_request()).text == "billing"


class ConfigTests:
    def test_a_target_needs_no_model_id(self):
        spec = ModelSpec.parse({"key": "p", "run": "pipe.py:answer"}, 0)
        assert spec.run == "pipe.py:answer"
        assert spec.model == "pipe.py:answer"  # identified by what it runs

    def test_targets_and_models_are_one_list(self, tmp_path, pipeline_dir):
        config = ProjectConfig.from_dict(
            {
                "project": "p",
                "models": [{"key": "m", "model": "mock:oracle"}],
                "targets": [{"key": "t", "run": "pipe.py:plain"}],
            },
            root=pipeline_dir,
        )
        assert [spec.key for spec in config.models] == ["m", "t"]
        assert config.models[1].base_dir == pipeline_dir

    def test_a_missing_target_file_fails_at_load_not_mid_sweep(self, tmp_path):
        """Loading validates, so a typo costs nothing instead of failing on case 1."""
        with pytest.raises(ConfigError, match="run target does not exist"):
            ProjectConfig.from_dict(
                {"project": "p", "targets": [{"key": "t", "run": "nope.py:answer"}]},
                root=tmp_path,
            )

    def test_a_malformed_run_spec_fails_at_load(self, tmp_path):
        with pytest.raises(ConfigError, match="run must be"):
            ProjectConfig.from_dict(
                {"project": "p", "targets": [{"key": "t", "run": "nocolon"}]}, root=tmp_path
            )

    def test_neither_models_nor_targets_is_an_error(self, tmp_path):
        with pytest.raises(ConfigError, match="at least one entry under"):
            ProjectConfig.from_dict({"project": "p"}, root=tmp_path)


class EndToEndTests:
    def test_a_pipeline_is_ranked_beside_a_model(self, tmp_path, pipeline_dir):
        root = tmp_path / "proj"
        write_project(
            root,
            {
                "project": "mixed",
                "models": [{"key": "model", "model": "mock:oracle"}],
                "targets": [{"key": "pipeline", "run": "pipe.py:plain"}],
                "run": {"trials": 1, "concurrency": 2, "retries": 0},
                "metrics": {"weights": {"accuracy": 1.0}},
                "scorers": {
                    "default": "classification",
                    "options": {"classification": {"labels": ["billing", "technical"]}},
                },
                "output": {"dir": "results", "formats": []},
            },
            [
                {"id": "t1", "input": "I was charged twice", "reference": "billing"},
                {"id": "t2", "input": "the app keeps crashing", "reference": "technical"},
            ],
        )
        (root / "pipe.py").write_text(
            (pipeline_dir / "pipe.py").read_text(encoding="utf-8"), encoding="utf-8"
        )

        result = ArenaRunner.from_project(root).run()
        board = result.leaderboard
        assert {e.key for e in board.entries} == {"model", "pipeline"}
        pipeline = board.get("pipeline")
        assert pipeline.status == "ranked"
        assert pipeline.raw("accuracy") == 1.0

    def test_reported_cost_beats_the_price_book_and_feeds_the_composite(
        self, tmp_path, pipeline_dir
    ):
        """A target's own spend must reach the cost metric — and be trusted."""
        root = tmp_path / "costed"
        write_project(
            root,
            {
                "project": "costed",
                "targets": [{"key": "pipeline", "run": "pipe.py:reports_usage"}],
                "run": {"trials": 1, "retries": 0},
                "metrics": {
                    "weights": {"accuracy": 0.5, "cost": 0.5},
                    "cost": {"budget_usd_per_1k_calls": 500.0},
                },
                "output": {"dir": "results", "formats": []},
            },
            [{"id": "t1", "input": "charged twice", "reference": "billing",
              "eval_type": "exact_match"}],
        )
        (root / "pipe.py").write_text(
            (pipeline_dir / "pipe.py").read_text(encoding="utf-8"), encoding="utf-8"
        )

        result = ArenaRunner.from_project(root).run()
        entry = result.leaderboard.get("pipeline")
        # 0.25 USD per call → 250 USD per 1,000 calls.
        assert entry.raw("cost") == pytest.approx(250.0)
        # The custom metric the pipeline emitted is weightable by name.
        assert entry.raw("agent_calls") == 3.0
        # Cost was measured, so it counts — no redistribution note.
        assert not any("Cost was left out" in note for note in result.leaderboard.notes)

    def test_a_target_that_raises_fails_its_call_not_the_run(self, tmp_path, pipeline_dir):
        root = tmp_path / "boom"
        write_project(
            root,
            {
                "project": "boom",
                "targets": [{"key": "bad", "run": "pipe.py:explodes"}],
                "models": [{"key": "ok", "model": "mock:oracle"}],
                "run": {"trials": 1, "retries": 0},
                "metrics": {"weights": {"accuracy": 1.0}},
                "output": {"dir": "results", "formats": []},
            },
            [{"id": "t1", "input": "say alpha", "reference": "alpha"}],
        )
        (root / "pipe.py").write_text(
            (pipeline_dir / "pipe.py").read_text(encoding="utf-8"), encoding="utf-8"
        )

        result = ArenaRunner.from_project(root).run()
        assert result.leaderboard.get("ok").status == "ranked"
        bad = result.leaderboard.get("bad")
        assert bad.status == "no_data"
        assert "pipeline blew up" in " ".join(bad.failures)


class ShippedExampleTests:
    """The pipeline_demo project is documentation; it has to keep working."""

    PROJECT = Path(__file__).resolve().parent.parent / "projects" / "pipeline_demo"

    def test_it_reproduces_the_studys_finding(self, tmp_path):
        config = ProjectConfig.load(self.PROJECT)
        config.output_dir = str(tmp_path)
        config.db_path = str(tmp_path / "arena.sqlite")
        config.formats = []
        board = ArenaRunner(config).run().leaderboard

        control = board.get("single_agent")
        handoff = board.get("peer_to_peer")
        summary = board.get("supervisor_worker")

        # The control sees the whole ticket, so it cannot lose the flag.
        assert control.raw("accuracy") == 1.0
        assert control.status == "ranked"

        # A rigid handoff with no slot for the flag always loses it; a free-text
        # summary loses it only sometimes — which is the harder bug to find.
        assert handoff.raw("accuracy") < summary.raw("accuracy") < 1.0
        assert handoff.status == "failed"
        assert summary.status == "failed"

        # More agents cost more, and the arena says so in money.
        assert control.raw("cost") < handoff.raw("cost") < summary.raw("cost")
