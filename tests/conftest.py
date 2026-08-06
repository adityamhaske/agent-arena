"""Shared fixtures for the arena test suite."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXAMPLE_PROJECTS = REPO_ROOT / "projects"


def write_project(
    root: Path,
    config: dict,
    tests: list[dict],
    *,
    extra_files: dict[str, str] | None = None,
) -> Path:
    """Materialise a project folder on disk. JSON everywhere, so these tests
    do not depend on PyYAML being installed."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (root / "tests.json").write_text(json.dumps(tests, indent=2), encoding="utf-8")
    for relative, content in (extra_files or {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


@pytest.fixture()
def simple_project(tmp_path: Path) -> Path:
    """A two-model project that runs fully offline."""
    return write_project(
        tmp_path / "simple",
        {
            "project": "simple",
            "models": [
                {"key": "perfect", "model": "mock:oracle"},
                {
                    "key": "half",
                    "model": "mock:coin",
                    "params": {"mode": "flaky", "accuracy": 50, "latency_ms": 100},
                },
            ],
            "defaults": {"max_tokens": 32},
            "run": {"trials": 1, "concurrency": 2, "retries": 0},
            "metrics": {"weights": {"accuracy": 1.0}},
            "output": {"dir": "results", "formats": []},
        },
        [
            {"id": "t1", "input": "say alpha", "reference": "alpha"},
            {"id": "t2", "input": "say beta", "reference": "beta"},
            {"id": "t3", "input": "say gamma", "reference": "gamma"},
            {"id": "t4", "input": "say delta", "reference": "delta"},
        ],
    )
