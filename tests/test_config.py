"""Config loading, validation and overrides."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_arena.core.config import ModelSpec, ProjectConfig
from agent_arena.core.errors import ConfigError

from .conftest import write_project


def test_loads_minimal_config(tmp_path: Path) -> None:
    root = write_project(
        tmp_path / "p",
        {"project": "p", "models": ["mock:oracle"]},
        [{"id": "a", "input": "hi", "reference": "hi"}],
    )
    config = ProjectConfig.load(root)

    assert config.project == "p"
    assert config.models[0].key == "mock:oracle"
    assert config.metrics.weights == {"accuracy": 1.0}
    assert config.run.trials == 1


def test_model_shorthand_and_longhand(tmp_path: Path) -> None:
    root = write_project(
        tmp_path / "p",
        {
            "project": "p",
            "models": [
                "claude-opus-5",
                {"key": "cheap", "model": "claude-haiku-4-5", "params": {"temperature": 0}},
            ],
        },
        [{"id": "a", "input": "hi", "reference": "hi"}],
    )
    config = ProjectConfig.load(root)

    assert [m.key for m in config.models] == ["claude-opus-5", "cheap"]
    assert config.models[1].model == "claude-haiku-4-5"
    assert config.models[1].params == {"temperature": 0}


def test_duplicate_model_keys_rejected(tmp_path: Path) -> None:
    root = write_project(
        tmp_path / "p",
        {"project": "p", "models": ["claude-opus-5", "claude-opus-5"]},
        [{"id": "a", "input": "hi", "reference": "hi"}],
    )
    with pytest.raises(ConfigError, match="duplicate model key"):
        ProjectConfig.load(root)


def test_missing_models_is_an_error(tmp_path: Path) -> None:
    root = write_project(tmp_path / "p", {"project": "p"}, [])
    with pytest.raises(ConfigError, match="at least one entry under"):
        ProjectConfig.load(root)


def test_missing_config_file_explains_itself(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(ConfigError, match="No config file"):
        ProjectConfig.load(tmp_path / "empty")


def test_weights_are_normalised_not_taken_literally(tmp_path: Path) -> None:
    root = write_project(
        tmp_path / "p",
        {
            "project": "p",
            "models": ["mock:oracle"],
            "metrics": {"weights": {"accuracy": 5, "cost": 3, "latency": 2}},
        },
        [{"id": "a", "input": "hi", "reference": "hi"}],
    )
    weights = ProjectConfig.load(root).metrics.normalized_weights()

    assert weights == pytest.approx({"accuracy": 0.5, "cost": 0.3, "latency": 0.2})


def test_negative_weight_rejected(tmp_path: Path) -> None:
    root = write_project(
        tmp_path / "p",
        {"project": "p", "models": ["mock:oracle"], "metrics": {"weights": {"cost": -1}}},
        [{"id": "a", "input": "hi", "reference": "hi"}],
    )
    with pytest.raises(ConfigError, match="must be >= 0"):
        ProjectConfig.load(root)


def test_budget_implies_target_normalisation(tmp_path: Path) -> None:
    root = write_project(
        tmp_path / "p",
        {
            "project": "p",
            "models": ["mock:oracle"],
            "metrics": {
                "weights": {"accuracy": 1, "cost": 1},
                "cost": {"budget_usd_per_1k_calls": 4.0},
            },
        },
        [{"id": "a", "input": "hi", "reference": "hi"}],
    )
    config = ProjectConfig.load(root)

    assert config.metrics.targets["cost"] == 4.0
    assert config.metrics.normalize_mode("cost") == "target"
    assert config.metrics.normalize_mode("latency") == "minmax"
    assert config.metrics.normalize_mode("accuracy") == "raw"


def test_target_normalisation_without_a_target_is_rejected(tmp_path: Path) -> None:
    root = write_project(
        tmp_path / "p",
        {
            "project": "p",
            "models": ["mock:oracle"],
            "metrics": {"weights": {"cost": 1}, "cost": {"normalize": "target"}},
        },
        [{"id": "a", "input": "hi", "reference": "hi"}],
    )
    with pytest.raises(ConfigError, match="no target/budget"):
        ProjectConfig.load(root)


def test_constraints_parse_nested_blocks(tmp_path: Path) -> None:
    root = write_project(
        tmp_path / "p",
        {
            "project": "p",
            "models": ["mock:oracle"],
            "constraints": {
                "min_accuracy": 0.8,
                "privacy": {"required": ["dpa", "zdr"]},
                "deployment": {
                    "required_features": ["json_mode"],
                    "min_context_tokens": 200000,
                },
            },
        },
        [{"id": "a", "input": "hi", "reference": "hi"}],
    )
    constraints = ProjectConfig.load(root).constraints

    assert constraints.min_accuracy == 0.8
    assert constraints.privacy_required == ["dpa", "zdr"]
    assert constraints.min_context_tokens == 200000
    assert constraints.any_static is True


def test_overrides_filter_models_and_settings(tmp_path: Path) -> None:
    root = write_project(
        tmp_path / "p",
        {"project": "p", "models": ["mock:oracle", {"key": "b", "model": "mock:echo"}]},
        [{"id": "a", "input": "hi", "reference": "hi"}],
    )
    config = ProjectConfig.load(root).apply_overrides(models=["b"], trials=5, limit=1)

    assert [m.key for m in config.models] == ["b"]
    assert config.run.trials == 5
    assert config.test_filter["limit"] == 1


def test_override_with_unknown_model_lists_the_options(tmp_path: Path) -> None:
    root = write_project(
        tmp_path / "p",
        {"project": "p", "models": ["mock:oracle"]},
        [{"id": "a", "input": "hi", "reference": "hi"}],
    )
    with pytest.raises(ConfigError, match="unknown model"):
        ProjectConfig.load(root).apply_overrides(models=["nope"])


def test_test_discovery_finds_conventional_files(tmp_path: Path) -> None:
    root = write_project(
        tmp_path / "p",
        {"project": "p", "models": ["mock:oracle"]},
        [{"id": "a", "input": "hi", "reference": "hi"}],
    )
    (root / "tests").mkdir()
    (root / "tests" / "extra.json").write_text(
        json.dumps([{"id": "b", "input": "yo", "reference": "yo"}]), encoding="utf-8"
    )
    found = {p.name for p in ProjectConfig.load(root).discover_test_files()}

    assert found == {"tests.json", "extra.json"}


def test_explicit_test_path_that_does_not_exist_is_rejected(tmp_path: Path) -> None:
    root = write_project(
        tmp_path / "p",
        {"project": "p", "models": ["mock:oracle"], "tests": {"paths": ["nope.jsonl"]}},
        [{"id": "a", "input": "hi", "reference": "hi"}],
    )
    with pytest.raises(ConfigError, match="does not exist"):
        ProjectConfig.load(root)


def test_database_path_defaults_under_output_dir(tmp_path: Path) -> None:
    root = write_project(
        tmp_path / "p",
        {"project": "p", "models": ["mock:oracle"], "output": {"dir": "out"}},
        [{"id": "a", "input": "hi", "reference": "hi"}],
    )
    config = ProjectConfig.load(root)

    assert config.database == root / "out" / "arena.sqlite"


def test_model_spec_requires_an_id() -> None:
    with pytest.raises(ConfigError, match="needs a 'model'"):
        ModelSpec.parse({"key": "x"}, 0)
