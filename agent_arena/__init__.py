"""Agent Arena — a universal, config-driven harness for comparing LLMs on *your* project.

The engine contains no project-specific logic. Point it at a folder holding a
``config.yaml`` and one or more test files and it will run every model against
every test case, score the outputs with pluggable scorers, and rank the models
by a weighted composite of accuracy, cost, latency and any custom metric you
emit.

Typical use::

    from agent_arena import run

    result = run("projects/support_triage")
    print(result.winner)

The core has no hard third-party dependencies: provider SDKs are imported
lazily, and PyYAML is optional (JSON config/test files work without it).
"""

from .core.config import ProjectConfig, load_config
from .core.errors import (
    ArenaError,
    ConfigError,
    ConnectorError,
    ScorerError,
    TestCaseError,
)
from .core.metrics import Leaderboard, ModelScore
from .core.runner import ArenaRunner, RunResult
from .core.testcase import TestCase, load_test_cases

__version__ = "2.0.0rc2"

__all__ = [
    "ArenaError",
    "ArenaRunner",
    "ConfigError",
    "ConnectorError",
    "Leaderboard",
    "ModelScore",
    "ProjectConfig",
    "RunResult",
    "ScorerError",
    "TestCase",
    "TestCaseError",
    "__version__",
    "evaluate",
    "load_config",
    "load_test_cases",
    "run",
]


def run(project_path, **overrides):
    """Evaluate a project folder and return a :class:`RunResult`.

    ``overrides`` are applied on top of the loaded config (e.g. ``trials=1``,
    ``models=["claude-opus-5"]``, ``limit=10``, ``concurrency=8``).
    """
    return ArenaRunner.from_project(project_path, **overrides).run()


#: Alias — ``arena evaluate`` on the CLI, ``evaluate()`` in Python.
evaluate = run
