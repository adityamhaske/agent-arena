"""Tests that a provider profile actually reaches the wire.

The `providers:` block parsed and resolved for a while before the runner did
anything with it, which is the worst state for a config field to be in: it reads
as working, validates cleanly, and silently changes nothing. These tests assert
on what the *server* received, not on what the config object holds, because that
is the only thing that distinguishes the two states.

The two-accounts case is the one the whole feature exists for — it was not
expressible at all before profiles.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agent_arena.connectors.registry import build_connector
from agent_arena.core.config import ProjectConfig
from agent_arena.core.errors import ConnectorError
from agent_arena.core.runner import ArenaRunner


class _Recorder(BaseHTTPRequestHandler):
    """An OpenAI-shaped endpoint that remembers what it was sent."""

    received: list[dict] = []

    def log_message(self, *args):  # noqa: A003 - quiet in tests
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).received.append(
            {
                "port": self.server.server_address[1],
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "org": self.headers.get("X-Org"),
                "model": body.get("model"),
            }
        )
        payload = json.dumps(
            {
                "choices": [{"message": {"content": "billing"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture()
def endpoints():
    """Two independent servers, standing in for two accounts."""
    _Recorder.received = []
    servers = []
    for _ in range(2):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
    try:
        yield [s.server_address[1] for s in servers], _Recorder
    finally:
        for httpd in servers:
            httpd.shutdown()
            httpd.server_close()


def _project(tmp_path: Path, providers, models) -> ProjectConfig:
    (tmp_path / "tests.yaml").write_text(
        json.dumps({"tests": [{"id": "t1", "input": "charged twice", "reference": "billing"}]}),
        encoding="utf-8",
    )
    return ProjectConfig.from_dict(
        {
            "project": "routing_probe",
            "providers": providers,
            "models": models,
            "run": {"trials": 1, "concurrency": 1},
            "scorers": {
                "default": "classification",
                "options": {"classification": {"labels": ["billing", "technical"]}},
            },
            "tests": ["tests.yaml"],
            "output": {"dir": "results"},
        },
        root=tmp_path,
    )


def test_two_accounts_on_one_vendor_compete_in_the_same_run(tmp_path, endpoints, monkeypatch):
    (port_a, port_b), recorder = endpoints
    monkeypatch.setenv("ARENA_WORK_KEY", "sk-work-account")
    monkeypatch.setenv("ARENA_PERSONAL_KEY", "sk-personal-account")

    config = _project(
        tmp_path,
        providers=[
            {"id": "work", "kind": "openai_compatible",
             "base_url": f"http://127.0.0.1:{port_a}/v1",
             "api_key": "${env:ARENA_WORK_KEY}", "headers": {"X-Org": "org-work"}},
            {"id": "personal", "kind": "openai_compatible",
             "base_url": f"http://127.0.0.1:{port_b}/v1",
             "api_key": "${env:ARENA_PERSONAL_KEY}", "headers": {"X-Org": "org-personal"}},
        ],
        models=[
            {"key": "gpt_work", "provider": "work", "model": "gpt-5"},
            {"key": "gpt_personal", "provider": "personal", "model": "gpt-5"},
        ],
    )
    ArenaRunner(config).run()

    by_port = {r["port"]: r for r in recorder.received}
    assert len(by_port) == 2, "both profiles must have been called"
    assert by_port[port_a]["authorization"] == "Bearer sk-work-account"
    assert by_port[port_b]["authorization"] == "Bearer sk-personal-account"


def test_profile_headers_reach_the_request(tmp_path, endpoints, monkeypatch):
    (port_a, port_b), recorder = endpoints
    monkeypatch.setenv("ARENA_WORK_KEY", "k")
    monkeypatch.setenv("ARENA_PERSONAL_KEY", "k")
    config = _project(
        tmp_path,
        providers=[
            {"id": "work", "kind": "openai_compatible",
             "base_url": f"http://127.0.0.1:{port_a}/v1",
             "api_key": "${env:ARENA_WORK_KEY}", "headers": {"X-Org": "org-work"}},
            {"id": "personal", "kind": "openai_compatible",
             "base_url": f"http://127.0.0.1:{port_b}/v1",
             "api_key": "${env:ARENA_PERSONAL_KEY}", "headers": {"X-Org": "org-personal"}},
        ],
        models=[
            {"key": "a", "provider": "work", "model": "gpt-5"},
            {"key": "b", "provider": "personal", "model": "gpt-5"},
        ],
    )
    ArenaRunner(config).run()
    orgs = {r["port"]: r["org"] for r in recorder.received}
    assert orgs[port_a] == "org-work"
    assert orgs[port_b] == "org-personal"


def test_model_prefix_rewrites_the_id_on_the_way_out(tmp_path, endpoints, monkeypatch):
    (port_a, _), recorder = endpoints
    monkeypatch.setenv("ARENA_KEY", "k")
    config = _project(
        tmp_path,
        providers=[
            {"id": "gw", "kind": "openai_compatible",
             "base_url": f"http://127.0.0.1:{port_a}/v1",
             "api_key": "${env:ARENA_KEY}", "model_prefix": "acme/"},
        ],
        models=[{"key": "m", "provider": "gw", "model": "gpt-5"}],
    )
    ArenaRunner(config).run()
    assert recorder.received[0]["model"] == "acme/gpt-5"


def test_a_reference_that_resolves_to_nothing_says_which_profile(tmp_path, monkeypatch):
    monkeypatch.delenv("ARENA_MISSING", raising=False)
    config = _project(
        tmp_path,
        providers=[{"id": "gw", "kind": "openai_compatible",
                    "base_url": "http://127.0.0.1:1/v1", "api_key": "${env:ARENA_MISSING}"}],
        models=[{"key": "m", "provider": "gw", "model": "gpt-5"}],
    )
    with pytest.raises(ConnectorError) as exc:
        build_connector(config.models[0], config.defaults, profile=config.providers[0])
    message = str(exc.value)
    assert "gw" in message and "ARENA_MISSING" in message


def test_the_resolved_key_is_never_echoed_in_an_error(tmp_path, monkeypatch):
    # The message names the *reference*, so a failure report cannot carry a
    # credential into a log or an issue tracker.
    monkeypatch.setenv("ARENA_SECRET", "sk-do-not-print-me")
    config = _project(
        tmp_path,
        providers=[{"id": "gw", "kind": "openai_compatible",
                    "base_url": "http://127.0.0.1:1/v1", "api_key": "${env:ARENA_SECRET}"}],
        models=[{"key": "m", "provider": "gw", "model": "gpt-5"}],
    )
    connector = build_connector(config.models[0], config.defaults, profile=config.providers[0])
    assert "sk-do-not-print-me" not in repr(connector)


def test_a_profile_supplies_transport_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_KEY", "k")
    config = _project(
        tmp_path,
        providers=[{"id": "gw", "kind": "openai_compatible",
                    "base_url": "http://127.0.0.1:1/v1", "api_key": "${env:ARENA_KEY}",
                    "proxy": "http://squid:3128", "verify_tls": False, "timeout_s": 42}],
        models=[{"key": "m", "provider": "gw", "model": "gpt-5"}],
    )
    connector = build_connector(config.models[0], config.defaults, profile=config.providers[0])
    assert connector.proxy == "http://squid:3128"
    assert connector.verify_tls is False
    assert connector.timeout_s == 42


def test_a_model_without_a_profile_routes_exactly_as_it_did_before(tmp_path):
    # The back-compat guarantee: v1 configs must be untouched by any of this.
    config = ProjectConfig.from_dict(
        {"project": "p", "models": [{"key": "m", "model": "mock:oracle"}],
         "tests": {"paths": []}},
        root=tmp_path,
    )
    assert config.provider_for(config.models[0]) is None
    connector = build_connector(config.models[0], config.defaults, profile=None)
    assert connector.provider == "mock"
    assert connector.headers == {}
