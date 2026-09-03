"""Tests for provider profiles.

The property worth defending: a raw key typed into a form must never land in a
plaintext settings file. `save_provider` moves it into the OS key store and
persists only the reference, and the test below asserts on the *bytes of the
file* rather than on the returned object, because the object is not what leaks.

`health_check` is tested for not raising as much as for succeeding. A settings
page that crashed when a gateway was down would be useless exactly when you
needed it.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent_arena.service import providers, settings
from agent_arena.service.errors import NotFoundError, ServiceError


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Never touch the developer's real settings or keyring."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # Force the file-backed store so tests do not write to a real OS keychain.
    monkeypatch.setattr("agent_arena.core.secrets._store_tool", lambda: None)
    return tmp_path


class _Models(BaseHTTPRequestHandler):
    payload: bytes = json.dumps({"data": [{"id": "gpt-5"}, {"id": "gpt-4o"}]}).encode()
    status: int = 200

    def log_message(self, *args):  # noqa: A003
        pass

    def do_GET(self):  # noqa: N802
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(type(self).payload)))
        self.end_headers()
        self.wfile.write(type(self).payload)


@pytest.fixture()
def endpoint():
    _Models.status = 200
    _Models.payload = json.dumps({"data": [{"id": "gpt-5"}, {"id": "gpt-4o"}]}).encode()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Models)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/v1", _Models
    finally:
        httpd.shutdown()
        httpd.server_close()


# ------------------------------------------------------------------- storage


def test_a_profile_round_trips():
    providers.save_provider({"id": "work", "kind": "openai", "api_key": "${env:K}"})
    stored = providers.get_provider("work")
    assert stored.kind == "openai"
    assert stored.api_key_ref == "${env:K}"


def test_a_literal_key_never_reaches_the_settings_file(isolated_config):
    providers.save_provider(
        {"id": "gw", "kind": "openai", "api_key": "sk-ant-typed-into-a-form"}
    )
    raw = settings.settings_path().read_bytes()
    assert b"sk-ant-typed-into-a-form" not in raw
    assert providers.get_provider("gw").api_key_ref == "${keyring:agent-arena/gw}"


def test_a_reference_is_stored_as_given():
    # It is already indirect, so there is nothing to move.
    providers.save_provider({"id": "w", "kind": "openai", "api_key": "${env:OPENAI_API_KEY}"})
    assert providers.get_provider("w").api_key_ref == "${env:OPENAI_API_KEY}"


def test_saving_the_same_id_replaces_rather_than_duplicates():
    providers.save_provider({"id": "w", "kind": "openai"})
    providers.save_provider({"id": "w", "kind": "anthropic"})
    assert [p.id for p in providers.user_providers()] == ["w"]
    assert providers.get_provider("w").kind == "anthropic"


def test_a_profile_without_an_id_is_refused():
    with pytest.raises(ServiceError):
        providers.save_provider({"kind": "openai"})


def test_one_malformed_entry_does_not_hide_the_others():
    providers.save_provider({"id": "good", "kind": "openai"})
    data = settings.load()
    data["providers"].append({"kind": "openai"})  # no id
    settings.save({"providers": data["providers"]})
    assert [p.id for p in providers.user_providers()] == ["good"]


# -------------------------------------------------------------------- delete


def test_deleting_a_profile_removes_it():
    providers.save_provider({"id": "w", "kind": "openai"})
    plan = providers.delete_provider("w")
    assert plan["deleted"] is True
    assert providers.user_providers() == []


def test_dry_run_leaves_the_profile_alone():
    providers.save_provider({"id": "w", "kind": "openai"})
    plan = providers.delete_provider("w", dry_run=True)
    assert plan["deleted"] is False
    assert [p.id for p in providers.user_providers()] == ["w"]


def test_purge_key_removes_the_stored_credential():
    from agent_arena.service.secrets import keyring_get

    providers.save_provider({"id": "gw", "kind": "openai", "api_key": "sk-literal"})
    assert keyring_get("agent-arena", "gw") == "sk-literal"
    providers.delete_provider("gw", purge_key=True)
    assert keyring_get("agent-arena", "gw") is None


def test_deleting_something_that_is_not_there_says_so():
    with pytest.raises(NotFoundError):
        providers.delete_provider("nope")


# -------------------------------------------------------------- health check


def test_health_check_reports_a_reachable_endpoint(endpoint):
    url, _ = endpoint
    profile = providers.save_provider({"id": "gw", "kind": "openai_compatible", "base_url": url})
    report = providers.health_check(profile)
    assert report["ok"] is True
    assert report["latency_ms"] is not None


def test_health_check_never_raises_on_a_refused_connection():
    profile = providers.save_provider(
        {"id": "dead", "kind": "openai_compatible", "base_url": "http://127.0.0.1:1/v1"}
    )
    report = providers.health_check(profile, timeout_s=1.0)
    assert report["ok"] is False
    assert report["error"]


def test_health_check_never_raises_on_a_server_error(endpoint):
    url, handler = endpoint
    handler.status = 500
    profile = providers.save_provider({"id": "gw", "kind": "openai_compatible", "base_url": url})
    report = providers.health_check(profile)
    assert report["ok"] is False
    assert report["status"] == 500


def test_a_missing_models_route_still_counts_as_reachable(endpoint):
    # Plenty of gateways do not implement /v1/models. Not being able to list
    # models is not the same as being down.
    url, handler = endpoint
    handler.status = 404
    profile = providers.save_provider({"id": "gw", "kind": "openai_compatible", "base_url": url})
    assert providers.health_check(profile)["ok"] is True


def test_health_check_does_not_echo_the_credential(monkeypatch):
    monkeypatch.setenv("ARENA_PROBE", "sk-ant-must-not-appear")
    profile = providers.save_provider(
        {"id": "dead", "kind": "openai_compatible",
         "base_url": "http://127.0.0.1:1/v1", "api_key": "${env:ARENA_PROBE}"}
    )
    report = providers.health_check(profile, timeout_s=1.0)
    assert "sk-ant-must-not-appear" not in json.dumps(report)


def test_a_profile_with_no_base_url_reports_rather_than_raising():
    profile = providers.save_provider({"id": "w", "kind": "openai"})
    report = providers.health_check(profile)
    assert report["ok"] is False and report["error"]


# ----------------------------------------------------------------- discovery


def test_discovery_lists_what_the_endpoint_serves(endpoint):
    url, _ = endpoint
    profile = providers.save_provider({"id": "gw", "kind": "openai_compatible", "base_url": url})
    assert providers.discover_models(profile) == ["gpt-4o", "gpt-5"]


def test_discovery_handles_a_bare_list(endpoint):
    url, handler = endpoint
    handler.payload = json.dumps(["a", "b"]).encode()
    profile = providers.save_provider({"id": "gw", "kind": "openai_compatible", "base_url": url})
    assert providers.discover_models(profile) == ["a", "b"]


def test_discovery_returns_nothing_rather_than_raising_when_unsupported(endpoint):
    url, handler = endpoint
    handler.status = 404
    profile = providers.save_provider({"id": "gw", "kind": "openai_compatible", "base_url": url})
    assert providers.discover_models(profile) == []
