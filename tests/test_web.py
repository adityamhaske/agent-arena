"""Tests for the browser UI's server side.

Two things are worth testing here and nothing else is:

* the **language layer**, because a wrong sentence in front of a non-technical
  user is worse than a raw number — they cannot tell it is wrong;
* the **API**, because it writes to the filesystem and spends money, and
  because a what-if that disagreed with a real run would quietly mislead.
"""

from __future__ import annotations

import json
import re
import threading
import time
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from agent_arena.web import language as lang
from agent_arena.web.api import ApiError, ArenaAPI
from agent_arena.web.server import build_app
from tests.conftest import write_project


# ---------------------------------------------------------------- language


class LanguageTests:
    def test_accuracy_reads_as_a_count(self):
        assert lang.out_of_100(0.833) == "83 out of 100"
        assert lang.out_of_100(1.0) == "100 out of 100"
        assert lang.out_of_100(None) == "not measured"

    def test_money_scales_to_something_picturable(self):
        assert lang.money(0) == "free"
        assert "under a cent" in lang.money(0.004)
        assert lang.money(0.06) == "6¢ per 1,000 uses"
        assert lang.money(12.5) == "$12.50 per 1,000 uses"

    def test_duration_and_feel(self):
        assert lang.duration(190) == "190 milliseconds"
        assert lang.duration(1500) == "1.5 seconds"
        assert lang.speed_word(190) == "instant"
        assert lang.speed_word(5000) == "a noticeable wait"

    def test_ratio_phrase_stays_quiet_when_the_gap_is_noise(self):
        assert lang.ratio_phrase(1.0, 1.05, "cheaper") is None
        assert lang.ratio_phrase(0.06, 0.30, "cheaper") == "5.0× cheaper"
        # Division by zero must not reach the user as a crash.
        assert lang.ratio_phrase(0, 5, "cheaper") is None
        assert lang.ratio_phrase(None, 5, "cheaper") is None

    def test_weights_sentence_is_ordered_by_importance(self):
        sentence = lang.explain_weights({"accuracy": 0.55, "cost": 0.25, "latency": 0.20})
        assert sentence.startswith("You care most about being right (55%)")
        assert sentence.index("staying cheap") < sentence.index("being fast")

    def test_constraint_keys_match_the_engine(self):
        """A requirement the UI names but the engine ignores would be a lie."""
        from agent_arena.core.config import Constraints

        sentences = lang.explain_constraints(
            {
                "min_accuracy": 0.7,
                "max_cost_per_1k_calls_usd": 2.0,
                "max_latency_p95_ms": 4000,
                "max_error_rate": 0.05,
            }
        )
        assert len(sentences) == 4
        for key in (
            "min_accuracy",
            "max_cost_per_1k_calls_usd",
            "max_latency_p95_ms",
            "max_error_rate",
        ):
            assert hasattr(Constraints, "__dataclass_fields__")
            assert key in Constraints.__dataclass_fields__

    def test_every_preset_names_a_real_scorer(self):
        from agent_arena.scorers.registry import ScorerRegistry

        available = set(ScorerRegistry().names)
        for preset in lang.JOB_PRESETS:
            assert preset["eval_type"] in available, preset["id"]

    def test_verdict_explains_the_trade_not_just_the_winner(self):
        board = {
            "weights": {"accuracy": 0.55, "cost": 0.25, "latency": 0.20},
            "notes": [],
            "entries": [
                _entry("small", 0.85, accuracy=0.83, cost=0.06, latency=190, rank=1),
                _entry("frontier", 0.75, accuracy=0.97, cost=0.30, latency=1500, rank=2),
                _entry("tiny", None, accuracy=0.50, cost=0.02, latency=90, status="failed",
                       failures=["accuracy 50.0% below the required 70.0%"]),
            ],
        }
        verdict = lang.explain_verdict(board)
        assert verdict["headline"] == "Use small."
        assert "83 out of 100" in verdict["body"]
        # The point of the tool: the winner is not the most accurate, and the
        # user must be told what they gave up.
        trade = " ".join(verdict["trade_offs"])
        assert "not the most accurate" in trade
        assert "cheaper" in trade and "faster" in trade
        assert verdict["confidence"] == "high"
        assert verdict["disqualified"][0]["headline"] == "Cannot use: tiny."
        assert "below the floor you set" in verdict["disqualified"][0]["reason"]

    def test_verdict_refuses_to_crown_a_winner_it_cannot_separate(self):
        board = {
            "weights": {"accuracy": 1.0},
            "notes": [],
            "entries": [
                _entry("a", 0.801, accuracy=0.80, rank=1),
                _entry("b", 0.800, accuracy=0.80, rank=2),
            ],
        }
        verdict = lang.explain_verdict(board)
        assert verdict["confidence"] == "low"
        assert "too close to call" in verdict["caveat"]

    def test_verdict_when_everything_was_ruled_out(self):
        board = {
            "weights": {"accuracy": 1.0},
            "notes": [],
            "entries": [_entry("a", None, accuracy=0.2, status="failed", failures=["accuracy low"])],
        }
        verdict = lang.explain_verdict(board)
        assert verdict["winner"] is None
        assert verdict["confidence"] == "none"
        assert "No model can be recommended" in verdict["headline"]


def _entry(key, composite, accuracy=None, cost=None, latency=None, rank=None,
           status="ranked", failures=None):
    metrics = {}
    for name, raw in (("accuracy", accuracy), ("cost", cost), ("latency", latency)):
        if raw is not None:
            metrics[name] = {"raw": raw, "normalized": raw, "weight": 0.3, "direction": "max"}
    return {
        "key": key, "display": key, "model": f"mock:{key}", "provider": "mock",
        "status": status, "composite": composite, "rank": rank, "metrics": metrics,
        "failures": failures or [], "warnings": [], "stats": {}, "by_tag": {},
    }


# --------------------------------------------------------------------- api


@pytest.fixture()
def api(tmp_path: Path, simple_project: Path) -> ArenaAPI:
    """An API rooted at a projects dir holding one offline project."""
    projects = tmp_path / "projects"
    projects.mkdir()
    write_project(
        projects / "demo",
        json.loads((simple_project / "config.json").read_text()),
        json.loads((simple_project / "tests.json").read_text()),
    )
    return ArenaAPI(projects)


class ApiSafetyTests:
    @pytest.mark.parametrize(
        "name", ["../escape", "a/b", "", "UPPER", "..", "with space", "x" * 65]
    )
    def test_a_project_name_cannot_escape_the_projects_directory(self, api, name):
        with pytest.raises(ApiError):
            api.describe_project(name)

    def test_writes_stay_inside_the_projects_directory(self, api, tmp_path):
        with pytest.raises(ApiError):
            api.create_project({"name": "../../etc/pwned", "preset": "sort",
                                "tests": [{"input": "x", "reference": "y"}]})
        assert not (tmp_path / "etc").exists()

    def test_missing_project_is_a_404_not_a_crash(self, api):
        with pytest.raises(ApiError) as caught:
            api.describe_project("nope")
        assert caught.value.status == 404

    def test_a_second_run_click_does_not_start_a_second_run(self, api):
        first = api.start_run("demo")
        second = api.start_run("demo")
        assert first["id"] == second["id"]
        _drain(api, first["id"])


class ApiProjectTests:
    def test_describe_speaks_plainly(self, api):
        described = api.describe_project("demo")
        assert described["name"] == "demo"
        assert described["weights_sentence"].startswith("You care")
        assert len(described["tests"]) == 4
        assert described["preflight"]["ok"] is True
        assert described["preflight"]["planned_calls"] == 8  # 2 models × 4 tests × 1 trial

    def test_wizard_writes_a_config_the_engine_can_load(self, api):
        created = api.create_project(
            {
                "name": "My New Thing!",
                "preset": "sort",
                "labels": ["yes", "no"],
                "weights": {"accuracy": 0.7, "cost": 0.3},
                "models": [{"key": "m", "model": "mock:oracle"}],
                "constraints": {"min_accuracy": 0.6},
                "tests": [
                    {"input": "is the sky blue", "reference": "yes"},
                    {"input": "is fire cold", "reference": "no"},
                ],
            }
        )
        assert created["name"] == "my_new_thing"
        # The proof it is a real project: the engine loads it and runs it.
        from agent_arena.core.runner import ArenaRunner

        runner = ArenaRunner.from_project(api.projects_dir / "my_new_thing")
        assert len(runner.test_cases) == 2
        assert runner.config.constraints.min_accuracy == 0.6

    def test_duplicate_test_ids_are_made_unique(self, api):
        created = api.create_project(
            {
                "name": "dupes", "preset": "sort", "labels": ["a", "b"],
                "models": [{"key": "m", "model": "mock:oracle"}],
                "tests": [
                    {"id": "same", "input": "one", "reference": "a"},
                    {"id": "same", "input": "two", "reference": "b"},
                ],
            }
        )
        ids = [t["id"] for t in created["tests"]]
        assert ids == ["same", "same_2"]

    def test_creating_over_an_existing_project_is_refused(self, api):
        with pytest.raises(ApiError) as caught:
            api.create_project({"name": "demo", "preset": "sort", "labels": ["a", "b"],
                                "tests": [{"input": "x", "reference": "a"}]})
        assert caught.value.status == 409

    def test_a_project_needs_at_least_one_example(self, api):
        with pytest.raises(ApiError):
            api.create_project({"name": "empty", "preset": "sort", "labels": ["a", "b"],
                                "tests": []})

    def test_editing_priorities_round_trips_through_the_config_file(self, api):
        api.update_project("demo", {"weights": {"accuracy": 0.5, "cost": 0.5},
                                    "constraints": {"min_accuracy": 0.9}, "trials": 2})
        described = api.describe_project("demo")
        assert described["weights"] == {"accuracy": 0.5, "cost": 0.5}
        assert described["constraints"]["min_accuracy"] == 0.9
        assert described["run"]["trials"] == 2

    def test_editing_examples_round_trips(self, api):
        api.save_tests("demo", {"tests": [{"id": "only", "input": "say alpha",
                                           "reference": "alpha"}]})
        described = api.describe_project("demo")
        assert [t["id"] for t in described["tests"]] == ["only"]

    def test_zero_weights_everywhere_is_refused(self, api):
        with pytest.raises(ApiError):
            api.update_project("demo", {"weights": {"accuracy": 0, "cost": 0}})


class ApiRunTests:
    def test_a_run_produces_a_verdict_and_stores_it(self, api):
        job = _drain(api, api.start_run("demo")["id"])
        assert job["status"] == "done", job.get("error")
        assert job["completed"] == 8
        result = job["result"]
        assert result["verdict"]["headline"].startswith("Use ")
        assert result["rows"]
        # The same run is retrievable afterwards without re-running anything.
        stored = api.stored_run("demo")
        assert stored["run_id"] == job["run_id"]

    def test_what_if_reranks_from_stored_answers_and_agrees_with_the_engine(self, api):
        _drain(api, api.start_run("demo")["id"])

        # Re-scoring with the project's own weights must reproduce the run
        # exactly — otherwise the what-if is telling a different story.
        same = api.rescore("demo", None, {"weights": {"accuracy": 1.0}})
        live = api.stored_run("demo")
        assert [r["key"] for r in same["rows"]] == [r["key"] for r in live["rows"]]
        assert same["rows"][0]["composite"] == pytest.approx(live["rows"][0]["composite"])
        assert same["hypothetical"] is True

    def test_what_if_can_change_the_winner(self, api):
        """The whole point of the slider: new priorities, new answer, no new spend.

        Needs a genuine trade-off, so this project pairs an accurate-but-slow
        model with a fast-but-worse one.
        """
        write_project(
            api.projects_dir / "tradeoff",
            {
                "project": "tradeoff",
                "models": [
                    {"key": "accurate", "model": "mock:flaky",
                     "params": {"accuracy": 100, "latency_ms": 2000}},
                    {"key": "quick", "model": "mock:flaky",
                     "params": {"accuracy": 50, "latency_ms": 20}},
                ],
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
        _drain(api, api.start_run("tradeoff")["id"])

        by_accuracy = api.rescore("tradeoff", None, {"weights": {"accuracy": 1.0}})
        by_speed = api.rescore("tradeoff", None, {"weights": {"latency": 1.0}})
        assert by_accuracy["rows"][0]["key"] == "accurate"
        assert by_speed["rows"][0]["key"] == "quick"

    def test_what_if_before_any_run_is_a_clear_404(self, api):
        api.create_project({"name": "fresh", "preset": "sort", "labels": ["a", "b"],
                            "models": [{"key": "m", "model": "mock:oracle"}],
                            "tests": [{"input": "x", "reference": "a"}]})
        with pytest.raises(ApiError) as caught:
            api.rescore("fresh", None, {"weights": {"accuracy": 1.0}})
        assert caught.value.status == 404

    def test_history_lists_past_runs(self, api):
        _drain(api, api.start_run("demo")["id"])
        history = api.history("demo")
        assert len(history["runs"]) == 1
        assert history["runs"][0]["winner"]


def _drain(api: ArenaAPI, job_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snapshot = api.job_status(job_id)
        if snapshot["status"] in ("done", "error"):
            return snapshot
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


# ------------------------------------------------------------------ server


@pytest.fixture()
def live_server(tmp_path: Path, simple_project: Path):
    projects = tmp_path / "served"
    projects.mkdir()
    write_project(
        projects / "demo",
        json.loads((simple_project / "config.json").read_text()),
        json.loads((simple_project / "tests.json").read_text()),
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), build_app(projects))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address
    finally:
        httpd.shutdown()
        httpd.server_close()


class ServerTests:
    def test_serves_the_app_shell_and_its_assets(self, live_server):
        for path, needle in (("/", b"Agent Arena"), ("/app.css", b"--accent"), ("/app.js", b"esc(")):
            status, _, body = _request(live_server, "GET", path)
            assert status == 200, path
            assert needle in body, path

    def test_unknown_paths_fall_back_to_the_app_shell(self, live_server):
        """Client-side routing must survive a refresh on a deep link."""
        status, _, body = _request(live_server, "GET", "/p/demo/results")
        assert status == 200
        assert b"<title>Agent Arena</title>" in body

    def test_static_serving_cannot_walk_out_of_the_static_folder(self, live_server):
        status, _, body = _request(live_server, "GET", "/../api.py")
        assert status == 200
        assert b"ArenaAPI" not in body  # served the shell, not the source

    def test_api_round_trip(self, live_server):
        status, _, body = _request(live_server, "GET", "/api/projects")
        assert status == 200
        assert json.loads(body)["projects"][0]["name"] == "demo"

    def test_unknown_endpoint_is_a_404_json_body(self, live_server):
        status, _, body = _request(live_server, "GET", "/api/nope")
        assert status == 404
        assert "error" in json.loads(body)

    def test_a_foreign_host_header_is_refused(self, live_server):
        status, _, _ = _request(live_server, "GET", "/api/projects",
                                headers={"Host": "attacker.example"})
        assert status == 403

    def test_malformed_json_is_a_message_not_a_stack_trace(self, live_server):
        status, _, body = _request(live_server, "POST", "/api/projects", raw=b"{not json")
        assert status == 400
        assert "JSON" in json.loads(body)["error"]

    def test_responses_carry_the_hardening_headers(self, live_server):
        _, headers, _ = _request(live_server, "GET", "/")
        assert "script-src 'self'" in headers["Content-Security-Policy"]
        assert headers["X-Content-Type-Options"] == "nosniff"


def _request(address, method, path, raw=None, headers=None):
    host, port = address
    connection = HTTPConnection(host, port, timeout=10)
    try:
        connection.request(method, path, body=raw, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


STATIC = Path(__file__).resolve().parents[1] / "agent_arena" / "web" / "static"


class ClientAssetContractTests:
    """Two bugs the Python suite could not see, because they lived in the
    static assets: a route table that could not match the links the app itself
    generated, and a CSS class defined twice with incompatible layouts.

    There is no JS runtime here on purpose — invariant 1 keeps the UI free of
    dependencies — so these read the assets as text and check the contracts
    that actually broke.
    """

    @staticmethod
    def _routes() -> list[re.Pattern[str]]:
        """The route table from app.js, as Python regexes."""
        js = (STATIC / "app.js").read_text()
        block = js[js.index("const routes = ["):]
        block = block[: block.index("\n];")]
        return [re.compile(pattern) for pattern in re.findall(r"\[/(\^.*?\$)/,", block)]

    def test_every_link_the_app_builds_matches_a_route(self):
        """A generated `#/...` href that no route matches is a dead link: the
        router falls through to `#/` and the user silently lands on Overview.
        That is how `#/p/<name>/results?run=<id>` broke — the query string was
        matched as part of the path, and no anchored pattern could ever match.
        """
        js = (STATIC / "app.js").read_text()
        routes = self._routes()
        assert routes, "no routes parsed out of app.js"

        dead = []
        for href in set(re.findall(r'href="(#/[^"]*)"', js)):
            path = href[1:].split("?", 1)[0]          # drop '#' and any query
            path = re.sub(r"\$\{[^{}]*\}", "sample", path)
            if "${" in path or "`" in path:
                continue                              # too dynamic to resolve here
            if not any(r.match(path) for r in routes):
                dead.append(href)
        assert not dead, f"links no route can match: {sorted(dead)}"

    def test_the_router_separates_the_query_string_from_the_path(self):
        js = (STATIC / "app.js").read_text()
        router = js[js.index("async function router()"):]
        router = router[: router.index("\n}")]
        assert "indexOf('?')" in router, "router must split the query off the hash"
        assert "URLSearchParams" in router, "parsed query must reach the view"

    def test_no_css_class_is_defined_with_two_different_display_modes(self):
        """`.stat-row` was declared once as a grid and again as a flex column.
        The later rule won, and every dashboard's four-up KPI cards collapsed
        into a single stacked column at full width.
        """
        css = (STATIC / "app.css").read_text()
        displays: dict[str, set[str]] = {}
        for selector, body in re.findall(r"^(\.[a-z0-9-]+)\s*\{([^}]*)\}", css, re.M):
            found = re.search(r"\bdisplay:\s*([a-z-]+)", body)
            if found:
                displays.setdefault(selector, set()).add(found.group(1))
        clashing = {sel: sorted(v) for sel, v in displays.items() if len(v) > 1}
        assert not clashing, f"same class, conflicting display: {clashing}"
