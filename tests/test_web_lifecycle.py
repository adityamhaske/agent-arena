"""Tests for the HTTP verbs that remove things.

Driven over real sockets rather than against ArenaAPI directly, because the
things most likely to be wrong here live in the server rather than the API: a
DELETE route is useless without a ``do_DELETE`` handler, and query-string flags
are the only way a DELETE carries options.

The traversal cases matter most. A project name and a run id both arrive
straight from a URL, and both end up in a path something is about to unlink.
"""

from __future__ import annotations

import json
import shutil
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from agent_arena.web.server import build_app

EXAMPLE = Path("projects/support_triage")


@pytest.fixture()
def client(tmp_path: Path):
    """A live server over a throwaway projects folder, plus a canary beside it."""
    root = tmp_path / "projects"
    root.mkdir()
    shutil.copytree(EXAMPLE, root / "support_triage",
                    ignore=shutil.ignore_patterns("results"))
    (tmp_path / "CANARY.txt").write_text("must survive", encoding="utf-8")
    # Produce a run rather than assuming the gitignored results/ directory is
    # there: it exists on a machine where sweeps have been run and nowhere else.
    from agent_arena.core.runner import ArenaRunner

    ArenaRunner.from_project(root / "support_triage").run()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), build_app(root))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]

    def call(method: str, path: str, body=None):
        conn = HTTPConnection("127.0.0.1", port, timeout=10)
        payload = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if payload else {}
        conn.request(method, path, payload, headers)
        response = conn.getresponse()
        raw = response.read().decode()
        conn.close()
        try:
            return response.status, json.loads(raw)
        except json.JSONDecodeError:
            return response.status, raw

    call.root = root  # type: ignore[attr-defined]
    call.port = port  # type: ignore[attr-defined]
    call.canary = tmp_path / "CANARY.txt"  # type: ignore[attr-defined]
    try:
        yield call
    finally:
        httpd.shutdown()
        httpd.server_close()


def _first_run_id(client) -> str:
    status, body = client("GET", "/api/projects/support_triage/runs?limit=1")
    assert status == 200
    assert body["runs"], "the client fixture should have produced a run"
    return body["runs"][0]["run_id"]


# ------------------------------------------------------------------- routing


def test_delete_is_actually_implemented(client):
    # Without do_DELETE on the handler this returns 501 and every delete route
    # below is decoration.
    status, _ = client("DELETE", "/api/projects/support_triage?dry_run=1")
    assert status == 200


# -------------------------------------------------------------------- dry run


def test_deleting_a_project_with_dry_run_changes_nothing(client):
    status, body = client("DELETE", "/api/projects/support_triage?dry_run=1")
    assert status == 200
    assert body["deleted"] is False
    assert body["bytes"] > 0
    assert (client.root / "support_triage").exists()


def test_deleting_a_run_with_dry_run_changes_nothing(client):
    run_id = _first_run_id(client)
    status, body = client("DELETE", f"/api/projects/support_triage/runs/{run_id}?dry_run=1")
    assert status == 200 and body["deleted"] is False

    status, after = client("GET", "/api/projects/support_triage/runs?limit=100")
    assert run_id in [row["run_id"] for row in after["runs"]]


# ------------------------------------------------------------------- deletes


def test_deleting_a_project_removes_it(client):
    status, body = client("DELETE", "/api/projects/support_triage")
    assert status == 200 and body["deleted"] is True
    assert not (client.root / "support_triage").exists()


def test_keep_results_leaves_the_database(client):
    status, _ = client("DELETE", "/api/projects/support_triage?keep_results=1")
    assert status == 200
    remaining = {p.name for p in (client.root / "support_triage").iterdir()}
    assert remaining == {"results"}


def test_deleting_a_run_hides_it_from_the_listing(client):
    run_id = _first_run_id(client)
    status, body = client("DELETE", f"/api/projects/support_triage/runs/{run_id}")
    assert status == 200 and body["deleted"] is True

    status, after = client("GET", "/api/projects/support_triage/runs?limit=100")
    assert run_id not in [row["run_id"] for row in after["runs"]]


# ----------------------------------------------------------------- traversal


@pytest.mark.parametrize(
    "path",
    [
        "/api/projects/..%2f..%2fCANARY.txt",
        "/api/projects/support_triage/runs/..%2f..%2f..%2fCANARY.txt",
        "/api/projects/.%2e/",
    ],
)
def test_a_traversing_path_never_deletes_anything(client, path):
    status, _ = client("DELETE", path)
    assert status != 200
    assert client.canary.exists()


# ------------------------------------------------------- duplicate & archive


def test_duplicating_a_project_does_not_carry_its_history(client):
    status, body = client(
        "POST", "/api/projects/support_triage/duplicate", {"name": "copy_one"}
    )
    assert status == 200
    assert body["runs"] == 0
    assert not (client.root / "copy_one" / "results").exists()


def test_duplicating_without_a_name_is_rejected(client):
    status, _ = client("POST", "/api/projects/support_triage/duplicate", {})
    assert status == 400


def test_archiving_hides_a_project_from_the_default_listing(client):
    client("POST", "/api/projects/support_triage/archive", {"archived": True})

    status, body = client("GET", "/api/projects")
    assert "support_triage" not in [p["name"] for p in body["projects"]]

    status, body = client("GET", "/api/projects?all=1")
    assert "support_triage" in [p["name"] for p in body["projects"]]


# -------------------------------------------------------------------- labels


def test_a_run_can_be_labelled_over_http(client):
    run_id = _first_run_id(client)
    status, body = client(
        f"POST", f"/api/projects/support_triage/runs/{run_id}/label",
        {"label": "before prompt change"},
    )
    assert status == 200 and body["label"] == "before prompt change"


# ------------------------------------------------------------------ settings


def test_settings_round_trip(client):
    status, before = client("GET", "/api/settings")
    assert status == 200 and "theme" in before

    status, after = client("PUT", "/api/settings", {"theme": "dark"})
    assert status == 200 and after["theme"] == "dark"


def test_settings_never_return_a_secret_value(client):
    # The response is serialised onto the wire, so a credential surviving this
    # call is a credential on the network.
    status, body = client("GET", "/api/settings")
    rendered = json.dumps(body)
    assert "sk-" not in rendered
    for profile in body.get("providers", []):
        assert "api_key" not in profile or str(profile.get("api_key", "")).startswith("${")


# ------------------------------------------------------------------- vacuum


def test_vacuum_reports_what_it_would_remove(client):
    run_id = _first_run_id(client)
    client("DELETE", f"/api/projects/support_triage/runs/{run_id}")

    status, plan = client("POST", "/api/projects/support_triage/vacuum?dry_run=1")
    assert status == 200 and plan["runs_removed"] == 1

    status, done = client("POST", "/api/projects/support_triage/vacuum")
    assert status == 200 and done["runs_removed"] == 1


# --------------------------------------------------------------- cross-site


def _raw(port: int, method: str, path: str, headers: dict) -> int:
    from http.client import HTTPConnection

    conn = HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path, b"{}", {"Content-Type": "application/json", **headers})
    status = conn.getresponse().status
    conn.close()
    return status


def test_a_cross_site_write_is_refused(client):
    """The Host allow-list does not cover this: a cross-site form POST carries
    a legitimate Host header. Without an Origin check the write still lands."""
    status = _raw(
        client.port,  # type: ignore[attr-defined]
        "POST",
        "/api/projects/support_triage/archive",
        {"Origin": "https://evil.example"},
    )
    assert status == 403


def test_a_same_origin_write_still_works(client):
    status = _raw(
        client.port,  # type: ignore[attr-defined]
        "POST",
        "/api/projects/support_triage/archive",
        {"Origin": f"http://127.0.0.1:{client.port}"},  # type: ignore[attr-defined]
    )
    assert status == 200


def test_a_request_with_no_origin_is_allowed(client):
    # Browsers omit Origin on same-origin navigations, and the CLI sends none.
    status = _raw(
        client.port,  # type: ignore[attr-defined]
        "POST",
        "/api/projects/support_triage/archive",
        {},
    )
    assert status == 200


def test_a_cross_site_read_is_still_allowed(client):
    # GET is not state-changing, and blocking it would break nothing useful
    # while breaking ordinary navigation.
    status = _raw(
        client.port,  # type: ignore[attr-defined]
        "GET",
        "/api/projects",
        {"Origin": "https://evil.example"},
    )
    assert status == 200
