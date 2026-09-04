"""Tests for detecting drift between a run and its own history.

A model choice decays: providers update models silently, prompts drift. This
is a *time-series* question about one model against its own past, which is
why it is a plain difference rather than the resampled comparison in
core/statistics.py — that module answers "are these two models really
different from each other in this run", not "did this one get worse".

The wording of `Drift.sentence` gets its own tests because a real bug lived
there during development: a disqualified model (a real, steady-state business
outcome) was reported the same way as a skipped or errored one, which reads as
"something is broken" when nothing is.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agent_arena.cli import main
from agent_arena.core.watch import compare_to_history, notify_webhook


def _row(composite, status="ranked"):
    return {"composite": composite, "status": status}


# ------------------------------------------------------------- the comparison


def test_the_first_run_has_no_baseline_to_compare_against():
    drift = compare_to_history("m", 0.85, "ranked", [_row(0.85)])
    assert drift.baseline_composite is None
    assert drift.flagged is False
    assert "first watch run" in drift.sentence


def test_a_small_change_is_not_flagged():
    history = [_row(0.83), _row(0.85), _row(0.84)]
    drift = compare_to_history("m", 0.83, "ranked", history, threshold=0.05)
    assert drift.flagged is False


def test_a_drop_past_the_threshold_is_flagged():
    history = [_row(0.40), _row(0.90), _row(0.90)]
    drift = compare_to_history("m", 0.40, "ranked", history, threshold=0.05)
    assert drift.flagged is True
    assert "dropped" in drift.sentence


def test_an_improvement_past_the_threshold_is_also_flagged():
    # Drift means "something changed enough to look at", not only regressions.
    history = [_row(0.95), _row(0.60), _row(0.60)]
    drift = compare_to_history("m", 0.95, "ranked", history, threshold=0.05)
    assert drift.flagged is True
    assert "improved by" in drift.sentence


def test_the_baseline_averages_several_prior_runs_not_only_the_last_one():
    # Averaging absorbs one noisy prior run instead of chasing it.
    history = [_row(0.80), _row(0.60), _row(1.00)]  # current, then two priors
    drift = compare_to_history("m", 0.80, "ranked", history, threshold=0.05)
    assert drift.baseline_composite == pytest.approx(0.80)
    assert drift.flagged is False


def test_a_status_change_is_flagged_even_with_no_composite():
    history = [_row(None, status="failed"), _row(0.90, status="ranked")]
    drift = compare_to_history("m", None, "failed", history)
    assert drift.flagged is True
    assert drift.status_changed is True
    assert "ranked -> failed" in drift.sentence


def test_staying_disqualified_across_runs_is_not_flagged():
    # A model that has been disqualified for weeks has not just changed.
    history = [_row(None, status="failed"), _row(None, status="failed")]
    drift = compare_to_history("m", None, "failed", history)
    assert drift.flagged is False


def test_disqualified_reads_as_a_real_outcome_not_a_failure():
    # The bug this test exists to catch: conflating "constraint failed" with
    # "the model could not be reached".
    drift = compare_to_history("m", None, "failed", [_row(None, status="failed")])
    assert "disqualified" in drift.sentence
    assert "skipped" not in drift.sentence


def test_a_skipped_model_is_worded_differently_from_a_disqualified_one():
    drift = compare_to_history("m", None, "no_data", [_row(None, status="no_data")])
    assert "skipped" in drift.sentence
    assert "disqualified" not in drift.sentence


def test_no_prior_runs_at_all_produces_no_baseline():
    drift = compare_to_history("m", 0.85, "ranked", [_row(0.85)])
    assert drift.n_baseline_runs == 0


def test_to_dict_carries_the_rendered_sentence():
    drift = compare_to_history("m", 0.85, "ranked", [_row(0.85), _row(0.80)])
    assert drift.to_dict()["sentence"] == drift.sentence


# --------------------------------------------------------------------- webhook


class _Hook(BaseHTTPRequestHandler):
    received: list = []
    status_to_return = 200

    def log_message(self, *args):  # noqa: A003
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        type(self).received.append(json.loads(self.rfile.read(length) or b"{}"))
        self.send_response(type(self).status_to_return)
        self.end_headers()


@pytest.fixture()
def hook():
    _Hook.received = []
    _Hook.status_to_return = 200
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Hook)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/hook", _Hook
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_webhook_receives_the_payload(hook):
    url, handler = hook
    error = notify_webhook(url, {"project": "p", "flagged": []})
    assert error is None
    assert handler.received == [{"project": "p", "flagged": []}]


def test_a_dead_webhook_returns_an_error_string_rather_than_raising():
    error = notify_webhook("http://127.0.0.1:1/nope", {}, timeout_s=1.0)
    assert error is not None


def test_a_webhook_error_status_is_reported_but_does_not_raise(hook):
    url, handler = hook
    handler.status_to_return = 500
    error = notify_webhook(url, {})
    # urllib treats 500 as an HTTPError, which is still a plain string here.
    assert error is not None


# ------------------------------------------------------------- config parsing


def test_watch_settings_default_to_a_sane_threshold():
    from agent_arena.core.config import ProjectConfig

    config = ProjectConfig.from_dict(
        {"project": "p", "models": [{"key": "m", "model": "mock:oracle"}], "tests": {"paths": []}},
        root=Path("."),
    )
    assert config.watch.drift_threshold == 0.05
    assert config.watch.webhook is None


def test_watch_settings_parse_from_config():
    from agent_arena.core.config import ProjectConfig

    config = ProjectConfig.from_dict(
        {
            "project": "p",
            "models": [{"key": "m", "model": "mock:oracle"}],
            "tests": {"paths": []},
            "watch": {"drift_threshold": 0.1, "webhook": "https://example.com/hook"},
        },
        root=Path("."),
    )
    assert config.watch.drift_threshold == 0.1
    assert config.watch.webhook == "https://example.com/hook"


def test_an_out_of_range_threshold_is_rejected():
    from agent_arena.core.config import ProjectConfig
    from agent_arena.core.errors import ConfigError

    with pytest.raises(ConfigError, match="watch.drift_threshold"):
        ProjectConfig.from_dict(
            {"project": "p", "models": [{"key": "m", "model": "mock:oracle"}],
             "tests": {"paths": []}, "watch": {"drift_threshold": 2.0}},
            root=Path("."),
        )


# -------------------------------------------------------------------- the CLI


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    (tmp_path / "tests.yaml").write_text(
        json.dumps({"tests": [{"id": f"t{i}", "input": f"c{i}", "reference": "billing"}
                              for i in range(20)]}),
        encoding="utf-8",
    )
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "project": "watch_probe",
                "models": [{"key": "m", "model": "mock:m",
                           "params": {"mode": "flaky", "accuracy": 90}}],
                "run": {"trials": 1, "concurrency": 2},
                "scorers": {"default": "classification",
                           "options": {"classification": {"labels": ["billing", "technical"]}}},
                "tests": ["tests.yaml"],
                "output": {"dir": "results"},
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_a_single_watch_tick_evaluates_and_reports(project: Path, capsys):
    assert main(["watch", "--project", str(project)]) == 0
    assert "watch_probe" in capsys.readouterr().out


def test_fail_on_drift_exits_nonzero_only_when_something_is_flagged(project: Path):
    main(["watch", "--project", str(project)])  # establishes a baseline

    config = json.loads((project / "config.json").read_text())
    config["models"][0]["params"]["accuracy"] = 20  # a real, large drop
    (project / "config.json").write_text(json.dumps(config))

    assert main(["watch", "--project", str(project), "--fail-on-drift"]) == 1


def test_without_fail_on_drift_the_exit_code_stays_zero(project: Path):
    main(["watch", "--project", str(project)])
    config = json.loads((project / "config.json").read_text())
    config["models"][0]["params"]["accuracy"] = 20
    (project / "config.json").write_text(json.dumps(config))
    assert main(["watch", "--project", str(project)]) == 0


def test_json_output_is_one_parseable_line_per_tick(project: Path, capsys):
    main(["watch", "--project", str(project), "--json"])
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["project"] == "watch_probe"
    assert "drifts" in payload


def test_a_drifting_run_notifies_the_configured_webhook(project: Path, hook):
    url, handler = hook
    main(["watch", "--project", str(project)])

    config = json.loads((project / "config.json").read_text())
    config["models"][0]["params"]["accuracy"] = 15
    (project / "config.json").write_text(json.dumps(config))

    main(["watch", "--project", str(project), "--webhook", url])
    assert len(handler.received) == 1
    assert handler.received[0]["flagged"]


def test_a_quiet_run_with_no_drift_prints_nothing_extra(project: Path, capsys):
    main(["watch", "--project", str(project), "--quiet"])
    # First tick has no baseline, so nothing is flagged and quiet suppresses it.
    assert capsys.readouterr().out.strip() == ""
