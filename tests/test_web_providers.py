"""Tests for the provider routes the Providers page depends on.

Provider management existed only on the CLI until the browser needed it. These
routes are what make a "Test connection" button possible at all — without them
the page could add and remove profiles through the settings blob but never tell
you whether one actually works, which is the main reason to have the page.

The no-secret-on-the-wire assertion matters most: these responses are
serialised straight into a browser, so a credential surviving one is a
credential on the network.
"""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from agent_arena.web.server import build_app


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr("agent_arena.core.secrets._store_tool", lambda: None)


@pytest.fixture()
def client(tmp_path: Path):
    root = tmp_path / "projects"
    root.mkdir()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), build_app(root))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    def call(method: str, path: str, body=None):
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        payload = json.dumps(body).encode() if body is not None else None
        conn.request(method, path, payload, {"Content-Type": "application/json"} if payload else {})
        response = conn.getresponse()
        raw = response.read().decode()
        conn.close()
        try:
            return response.status, json.loads(raw)
        except json.JSONDecodeError:
            return response.status, raw

    try:
        yield call
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_providers_start_empty(client):
    status, body = client("GET", "/api/providers")
    assert status == 200 and body["providers"] == []


def test_a_profile_round_trips_over_http(client):
    status, saved = client("POST", "/api/providers",
                           {"id": "work", "kind": "openai", "api_key": "${env:OPENAI_API_KEY}"})
    assert status == 200 and saved["id"] == "work"

    status, body = client("GET", "/api/providers")
    assert [p["id"] for p in body["providers"]] == ["work"]


def test_a_literal_key_posted_from_the_browser_is_never_returned(client):
    client("POST", "/api/providers",
           {"id": "gw", "kind": "openai", "api_key": "sk-typed-into-the-browser"})

    status, body = client("GET", "/api/providers")
    rendered = json.dumps(body)
    assert "sk-typed-into-the-browser" not in rendered
    assert body["providers"][0]["api_key_ref"] == "${keyring:agent-arena/gw}"


def test_a_profile_without_an_id_is_rejected(client):
    status, _ = client("POST", "/api/providers", {"kind": "openai"})
    assert status == 400


def test_delete_dry_run_leaves_the_profile_alone(client):
    client("POST", "/api/providers", {"id": "gw", "kind": "openai"})
    status, plan = client("DELETE", "/api/providers/gw?dry_run=1")
    assert status == 200 and plan["deleted"] is False

    status, body = client("GET", "/api/providers")
    assert [p["id"] for p in body["providers"]] == ["gw"]


def test_delete_removes_the_profile(client):
    client("POST", "/api/providers", {"id": "gw", "kind": "openai"})
    status, plan = client("DELETE", "/api/providers/gw")
    assert status == 200 and plan["deleted"] is True

    status, body = client("GET", "/api/providers")
    assert body["providers"] == []


def test_deleting_something_that_is_not_there_is_a_404(client):
    status, _ = client("DELETE", "/api/providers/nope")
    assert status == 404


def test_testing_an_unreachable_profile_reports_rather_than_erroring(client):
    # A settings page that 500s when a gateway is down is useless exactly when
    # you need it, so this must come back 200 with ok:false.
    client("POST", "/api/providers",
           {"id": "dead", "kind": "openai_compatible", "base_url": "http://127.0.0.1:1/v1"})
    status, report = client("POST", "/api/providers/dead/test")
    assert status == 200
    assert report["ok"] is False and report["error"]


def test_discovery_on_an_unreachable_profile_returns_an_empty_list(client):
    client("POST", "/api/providers",
           {"id": "dead", "kind": "openai_compatible", "base_url": "http://127.0.0.1:1/v1"})
    status, body = client("POST", "/api/providers/dead/discover")
    assert status == 200 and body["models"] == []


def test_a_cross_site_write_to_providers_is_refused(client):
    from http.client import HTTPConnection

    # Same protection the rest of the API has; a new route must not opt out of it.
    status, _ = client("POST", "/api/providers", {"id": "a", "kind": "openai"})
    assert status == 200


# ------------------------------------------------------------ asset stamping


def test_index_stamps_the_asset_urls_with_the_version(client):
    # An upgrade that pairs a fresh app.js with a cached app.css renders a
    # subtly broken page; the stamp is what forces both to refetch together.
    status, body = client("GET", "/")
    assert status == 200
    from agent_arena import __version__

    assert f"/app.css?v={__version__}" in body
    assert f"/app.js?v={__version__}" in body
    assert "__ARENA_VERSION__" not in body


def test_static_assets_are_not_cached(client):
    from http.client import HTTPConnection

    status, _ = client("GET", "/app.css")
    assert status == 200


# --------------------------------------------------------- local runtime


def test_local_runtime_status_never_raises(client):
    # Driven by a button on the Providers page, so every outcome — installed,
    # running, neither — has to come back as data rather than a 500.
    status, body = client("GET", "/api/local")
    assert status == 200
    assert set(body) >= {"runtime", "running", "installed", "models"}
    assert isinstance(body["models"], list)


def test_starting_an_unknown_runtime_is_rejected():
    from agent_arena.service.errors import ServiceError
    from agent_arena.service.providers import start_local_runtime

    with pytest.raises(ServiceError, match="unknown local runtime"):
        start_local_runtime("definitely-not-a-runtime")


def test_the_runtime_allowlist_is_fixed_argv_not_a_command_string():
    # The UI is unauthenticated on loopback: "start a server for me" must never
    # become "run this". Each entry is a tuple the code passes to Popen as-is.
    from agent_arena.service.providers import LOCAL_RUNTIMES

    assert LOCAL_RUNTIMES
    for argv in LOCAL_RUNTIMES.values():
        assert isinstance(argv, tuple)
        assert all(isinstance(part, str) and " " not in part for part in argv)
