"""Regressions for the issues found reviewing the initial universal-arena commits.

Each test here failed before its fix. Grouped in one file so the connection
between them stays visible: they are all cases the original 198 tests did not
reach.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from agent_arena import run
from agent_arena.cli import TEMPLATE_DIR, main
from agent_arena.connectors import GenerationRequest, PriceBook
from agent_arena.connectors.local import LocalConnector
from agent_arena.connectors.providers import OpenAIConnector
from agent_arena.connectors.registry import resolve_provider
from agent_arena.core.config import ModelSpec, ProjectConfig
from agent_arena.core.errors import ScorerError
from agent_arena.core.metrics import ModelScore, build_leaderboard
from agent_arena.core.report import Report
from agent_arena.core.runner import CallResult
from agent_arena.core.store import ResultStore
from agent_arena.scorers.registry import ScorerRegistry
from agent_arena.scorers.base import ScoringContext
from agent_arena.core.testcase import TestCase

from .conftest import write_project


# ---- pricing: overrides must not be reverted by the catalog ----------------


def test_second_override_does_not_revert_the_first() -> None:
    """A negotiated price, then an unrelated tweak, used to restore the
    catalog's price for the field the second call did not mention."""
    book = PriceBook()
    book.merge_overrides("claude-opus-5", {"input_usd_per_mtok": 12.0})
    book.merge_overrides("claude-opus-5", {"context_tokens": 500_000})

    card = book.get("claude-opus-5")
    assert card.input_usd_per_mtok == 12.0        # was silently back to 5.0
    assert card.context_tokens == 500_000


def test_short_price_aliases_are_not_shadowed_by_the_catalog() -> None:
    book = PriceBook()
    book.merge_overrides("claude-opus-5", {"input": 2.0, "output": 8.0})
    card = book.get("claude-opus-5")

    assert card.input_usd_per_mtok == 2.0
    assert card.output_usd_per_mtok == 8.0


# ---- report: a ranked model may have no composite -------------------------


def test_report_survives_a_winner_with_no_composite(tmp_path: Path) -> None:
    """Every weighted metric unmeasurable → composite is None. Crashing here
    threw away a sweep the user had already paid for."""
    project = write_project(
        tmp_path / "nocomp",
        {
            "project": "nocomp",
            "models": [{"key": "m", "model": "mock:oracle"}],
            "metrics": {"weights": {"some_metric_nobody_emits": 1.0}},
            "output": {"formats": []},
        },
        [{"id": "a", "input": "q", "reference": "a"}],
    )
    result = run(project)
    assert result.leaderboard.get("m").composite is None

    markdown = Report(result).markdown()      # used to raise TypeError
    assert "not scored" in markdown
    assert Report(result).console()


def test_tradeoff_sentence_handles_missing_composites() -> None:
    winner = ModelScore(key="a", model="m", composite=None)
    runner_up = ModelScore(key="b", model="m", composite=None)

    class Stub:
        config = None

    report = Report.__new__(Report)
    report.config = _MinimalConfig()
    report.weighted_metrics = []
    assert "closest alternative" in report._tradeoff_sentence(winner, runner_up)


class _MinimalConfig:
    class metrics:  # noqa: D106
        @staticmethod
        def direction(_name: str) -> str:
            return "max"


# ---- openai connector: control flag must not reach the provider -----------


def test_send_temperature_flag_never_leaks_into_the_payload() -> None:
    """`and` short-circuits when temperature is None, which used to leave this
    internal flag in the request body."""
    captured: dict = {}

    class FakeCompletions:
        def create(self, **payload):
            captured.update(payload)
            return type(
                "R",
                (),
                {
                    "choices": [
                        type("C", (), {
                            "message": type("M", (), {"content": "hi"})(),
                            "finish_reason": "stop",
                        })()
                    ],
                    "usage": None,
                    "model": "gpt-x",
                },
            )()

    connector = OpenAIConnector("gpt-x", send_temperature=False)
    connector._client = type(
        "Client", (), {"chat": type("Chat", (), {"completions": FakeCompletions()})()}
    )()

    connector.generate(GenerationRequest(messages=[{"role": "user", "content": "q"}]))
    assert "send_temperature" not in captured


# ---- local connector: HTTPError is a subclass of URLError ------------------


def test_a_server_without_a_models_route_is_not_reported_as_down() -> None:
    """llama.cpp and some vLLM builds 404 /v1/models. That is not 'unreachable',
    and reporting it as such skipped a perfectly usable server."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:
            pass

        def do_GET(self) -> None:  # noqa: N802
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}/v1"
        assert LocalConnector("any-model", api_base=base).healthcheck() is None
    finally:
        httpd.shutdown()
        httpd.server_close()


# ---- provider aliases resolve to one canonical card -----------------------


@pytest.mark.parametrize("provider", ["local", "ollama", "lmstudio"])
def test_local_provider_spellings_find_the_same_card(provider: str) -> None:
    spec = ModelSpec(key="k", model="some-local-model", provider=provider)
    card = PriceBook().get(spec.model, provider=resolve_provider(spec))

    assert card.known is True
    assert card.has_pricing is True                  # $0, not "unknown"
    assert card.privacy.get("on_prem") is True


# ---- runner: a failed run must not stay 'running' -------------------------


BOOM_HOOK = '''
def post_process(output, test_case, context):
    raise RuntimeError("hook exploded")
'''


def test_an_aborted_run_is_closed_out_not_left_running(tmp_path: Path) -> None:
    project = write_project(
        tmp_path / "aborted",
        {
            "project": "aborted",
            "models": [{"key": "m", "model": "mock:oracle"}],
            "hooks": {"post_process": "hooks.py:post_process"},
            "run": {"fail_fast": True, "retries": 0},
            "output": {"formats": []},
        },
        [{"id": "a", "input": "q", "reference": "a"}],
        extra_files={"hooks.py": BOOM_HOOK},
    )
    config = ProjectConfig.load(project)

    with pytest.raises(Exception):
        run(project)

    with ResultStore(config.database) as store:
        runs = store.runs("aborted")
        assert runs, "the run row should still exist"
        assert runs[0]["status"] == "aborted"       # was stuck at 'running'
        assert runs[0]["finished_at"] is not None


# ---- scorers: degenerate inputs --------------------------------------------


def test_empty_list_reference_is_a_clear_error_not_an_indexerror() -> None:
    scorer = ScorerRegistry().get("exact_match")
    context = ScoringContext(test_case=TestCase(id="t", input="q", reference=[]))

    with pytest.raises(ScorerError, match="empty list"):
        scorer("anything", [], context)


def test_judge_score_with_a_thousands_separator_parses() -> None:
    """A judge replying '1,000' used to raise a bare ValueError mid-run."""
    context = ScoringContext(
        test_case=TestCase(id="t", input="q"),
        judge=lambda prompt, system=None: "I would score this 1,000 out of 1000.",
    )
    result = ScorerRegistry().get("llm_judge")("a", "b", context)
    assert 0.0 <= result.score <= 1.0


# ---- config: a zero budget is a real ceiling ------------------------------


def test_a_zero_budget_is_honoured_not_skipped(tmp_path: Path) -> None:
    """`or`-chaining dropped a legitimate 0, silently downgrading an absolute
    gate to a relative min-max ranking."""
    project = write_project(
        tmp_path / "zero",
        {
            "project": "zero",
            "models": ["mock:oracle"],
            "metrics": {"weights": {"cost": 1.0}, "cost": {"budget_usd_per_1k_calls": 0}},
        },
        [{"id": "a", "input": "q", "reference": "a"}],
    )
    config = ProjectConfig.load(project)

    assert config.metrics.targets["cost"] == 0.0
    assert config.metrics.normalize_mode("cost") == "target"


# ---- store: flakiness is a within-run property ----------------------------


def test_flaky_tests_does_not_conflate_separate_runs(tmp_path: Path) -> None:
    """A prompt change between runs is a config difference, not trial
    flakiness, and must not be reported as one."""
    with ResultStore(tmp_path / "arena.sqlite") as store:
        for score in (1.0, 0.0):          # same case, different runs
            run_id = store.start_run("p", models=["m"], n_tests=1, weights={})
            store.record_result(
                run_id,
                "p",
                CallResult(
                    model_key="m", model="m", test_id="t", trial=1,
                    status="ok", score=score, passed=score > 0.5,
                ),
            )
        assert store.flaky_tests("p") == []


def test_flaky_tests_still_catches_within_run_variance(tmp_path: Path) -> None:
    with ResultStore(tmp_path / "arena.sqlite") as store:
        run_id = store.start_run("p", models=["m"], n_tests=1, weights={})
        for trial, score in enumerate((1.0, 0.0), start=1):
            store.record_result(
                run_id,
                "p",
                CallResult(
                    model_key="m", model="m", test_id="t", trial=trial,
                    status="ok", score=score, passed=score > 0.5,
                ),
            )
        flaky = store.flaky_tests("p")
        assert len(flaky) == 1
        assert flaky[0]["test_id"] == "t"


# ---- cli: --run-id must not be limited to a page --------------------------


def test_report_finds_an_older_run_by_id(simple_project: Path, capsys) -> None:
    main(["evaluate", "--project", str(simple_project), "--quiet", "--no-report"])
    config = ProjectConfig.load(simple_project)
    with ResultStore(config.database) as store:
        first_run = store.runs("simple")[0]["run_id"]

    # Bury it behind more runs than a single page would show.
    for _ in range(3):
        main(["evaluate", "--project", str(simple_project), "--quiet", "--no-report"])
    capsys.readouterr()

    assert main(["report", "--project", str(simple_project), "--run-id", first_run]) == 0
    assert first_run in capsys.readouterr().out


# ---- report: failures on later trials must be visible ---------------------


def test_failures_on_later_trials_appear_in_the_report(tmp_path: Path) -> None:
    """The section filtered to trial 1, hiding exactly the flaky failures that
    most deserve a look."""
    project = write_project(
        tmp_path / "latetrial",
        {
            "project": "latetrial",
            "models": [
                {
                    "key": "m",
                    "model": "mock:flaky",
                    "params": {"mode": "flaky", "accuracy": 50},
                }
            ],
            "run": {"trials": 4},
            "output": {"formats": []},
        },
        [{"id": f"t{i}", "input": "q", "reference": "expected"} for i in range(6)],
    )
    result = run(project)
    failures = [r for r in result.results if r.passed is False]
    assert failures, "the flaky mock should fail something"

    markdown = Report(result).markdown()
    assert "Where models went wrong" in markdown
    # Every failing test id should be listed, whichever trial it failed on.
    failing_ids = {r.test_id for r in failures}
    listed = {tid for tid in failing_ids if f"`{tid}`" in markdown}
    assert listed == failing_ids


# ---- packaging: the template ships inside the wheel -----------------------


def test_template_lives_inside_the_package() -> None:
    """`projects/` is not part of the wheel, so a template out there made
    `arena init` fail on every pip install."""
    assert TEMPLATE_DIR.is_dir()
    assert TEMPLATE_DIR.is_relative_to(Path(sys.modules["agent_arena"].__file__).parent)
    assert (TEMPLATE_DIR / "config.yaml").is_file()
    assert (TEMPLATE_DIR / "tests.yaml").is_file()


def test_template_is_declared_as_package_data() -> None:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    body = pyproject.read_text(encoding="utf-8")
    assert "templates/*" in body
