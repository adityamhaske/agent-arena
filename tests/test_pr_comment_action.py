"""Tests for the PR-comment script behind the published GitHub Action.

This script ships outside `agent_arena/` (in `.github/actions/`) because it
belongs to the CI-facing surface, not the installable package, but it is real
logic — merging two different JSON shapes and driving two GitHub API calls —
and a real bug lived in it during development: the PATCH url was built with a
`.replace()` call that replaced a string with itself, a no-op that a
hand-written smoke test of `render_table` alone would never have caught.
That is why `upsert_comment` is tested against a real local HTTP server rather
than only inspecting the URL string.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ACTION_DIR = Path(__file__).resolve().parent.parent / ".github" / "actions" / "agent-arena-eval"
sys.path.insert(0, str(ACTION_DIR))
import pr_comment  # noqa: E402


# ------------------------------------------------------------------- parsing


def test_result_json_is_keyed_by_key(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps({
        "leaderboard": {"entries": [{"key": "a", "status": "ranked", "composite": 0.9}]}
    }))
    assert pr_comment._entries_from_result(str(path)) == {"a": {"status": "ranked", "composite": 0.9}}


def test_baseline_json_is_keyed_by_model_key_not_key(tmp_path):
    # The export format uses a different field name than the evaluate --json
    # format. Reading the wrong one would silently produce an empty baseline.
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({
        "rankings": [{"model_key": "a", "status": "ranked", "composite": 0.8}]
    }))
    assert pr_comment._entries_from_baseline(str(path)) == {"a": {"status": "ranked", "composite": 0.8}}


# --------------------------------------------------------------------- table


def test_the_table_ranks_before_disqualifying():
    current = {
        "b": {"status": "failed", "composite": None},
        "a": {"status": "ranked", "composite": 0.9},
    }
    table = pr_comment.render_table(current, None)
    assert table.index("`a`") < table.index("`b`")


def test_no_baseline_means_no_delta_column():
    table = pr_comment.render_table({"a": {"status": "ranked", "composite": 0.9}}, None)
    assert "delta" not in table


def test_an_improvement_shows_a_positive_delta():
    current = {"a": {"status": "ranked", "composite": 0.9}}
    baseline = {"a": {"status": "ranked", "composite": 0.8}}
    table = pr_comment.render_table(current, baseline)
    assert "+0.100" in table


def test_a_regression_shows_a_negative_delta():
    current = {"a": {"status": "ranked", "composite": 0.7}}
    baseline = {"a": {"status": "ranked", "composite": 0.9}}
    table = pr_comment.render_table(current, baseline)
    assert "-0.200" in table


def test_a_new_model_not_in_the_baseline_is_called_out():
    current = {"a": {"status": "ranked", "composite": 0.9}, "new": {"status": "ranked", "composite": 0.5}}
    baseline = {"a": {"status": "ranked", "composite": 0.9}}
    assert "New this run: new" in pr_comment.render_table(current, baseline)


def test_a_model_removed_since_the_baseline_is_called_out():
    current = {"a": {"status": "ranked", "composite": 0.9}}
    baseline = {"a": {"status": "ranked", "composite": 0.9}, "gone": {"status": "ranked", "composite": 0.1}}
    assert "No longer present: gone" in pr_comment.render_table(current, baseline)


def test_a_disqualified_model_with_no_composite_shows_an_em_dash_delta():
    current = {"a": {"status": "failed", "composite": None}}
    baseline = {"a": {"status": "ranked", "composite": 0.9}}
    table = pr_comment.render_table(current, baseline)
    assert "| — |" in table


# ---------------------------------------------------------------- the marker


def test_every_posted_body_carries_the_marker():
    # Without it, every push would post a new comment instead of updating one.
    assert pr_comment.MARKER.startswith("<!--")


# ------------------------------------------------------------- against a real server


class _GitHub(BaseHTTPRequestHandler):
    """Stands in for api.github.com: list comments, then create or update one."""

    comments: list = []
    calls: list = []

    def log_message(self, *args):  # noqa: A003
        pass

    def do_GET(self):  # noqa: N802
        type(self).calls.append(("GET", self.path))
        body = json.dumps(type(self).comments).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        self._handle_write("POST")

    def do_PATCH(self):  # noqa: N802
        self._handle_write("PATCH")

    def _handle_write(self, method):
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        type(self).calls.append((method, self.path, payload))
        if method == "PATCH":
            comment_id = int(self.path.rsplit("/", 1)[-1])
            for comment in type(self).comments:
                if comment["id"] == comment_id:
                    comment["body"] = payload["body"]
        else:
            type(self).comments.append({"id": 1, "body": payload["body"]})
        body = json.dumps({"id": 1}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def github(monkeypatch):
    _GitHub.comments = []
    _GitHub.calls = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _GitHub)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    monkeypatch.setattr(pr_comment, "_api", _bind_api(base))
    try:
        yield _GitHub
    finally:
        httpd.shutdown()
        httpd.server_close()


def _bind_api(base):
    """Redirect the real api.github.com URLs the code builds onto the fixture."""
    real = pr_comment._api

    def patched(method, url, token, body=None):
        url = url.replace("https://api.github.com", base)
        return real(method, url, token, body)

    return patched


def test_a_first_comment_is_created(github):
    pr_comment.upsert_comment("me/repo", 7, "tok", "hello")
    assert [c["method"] if False else c[0] for c in github.calls] == ["GET", "POST"]
    assert github.comments[0]["body"] == f"{pr_comment.MARKER}\nhello"


def test_a_second_call_updates_the_same_comment_via_patch(github):
    # This is the case the URL-construction bug broke: PATCH must hit
    # /issues/comments/{id}, not a mangled /issues/{pr}/comments path.
    pr_comment.upsert_comment("me/repo", 7, "tok", "first")
    pr_comment.upsert_comment("me/repo", 7, "tok", "second")

    assert len(github.comments) == 1, "a second push must update, not duplicate"
    assert github.comments[0]["body"] == f"{pr_comment.MARKER}\nsecond"
    methods = [call[0] for call in github.calls]
    assert methods == ["GET", "POST", "GET", "PATCH"]


def test_the_patch_request_targets_the_comment_id_not_the_pr_number(github):
    pr_comment.upsert_comment("me/repo", 999, "tok", "first")
    pr_comment.upsert_comment("me/repo", 999, "tok", "second")
    patch_call = next(c for c in github.calls if c[0] == "PATCH")
    assert patch_call[1].endswith("/issues/comments/1")
    assert "/999/" not in patch_call[1]


# ------------------------------------------------------- extract_outputs.py


def test_extract_outputs_reports_the_winner(tmp_path):
    import subprocess

    result = tmp_path / "result.json"
    result.write_text(json.dumps({
        "leaderboard": {"entries": [
            {"key": "a", "status": "ranked", "composite": 0.853},
            {"key": "b", "status": "failed", "composite": None},
        ]}
    }))
    script = ACTION_DIR / "extract_outputs.py"
    out = subprocess.run(
        [sys.executable, str(script), str(result)],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "composite=0.8530" in out
    assert "winner=a" in out


def test_extract_outputs_when_nothing_is_ranked(tmp_path):
    # Every model disqualified is a real outcome, and $GITHUB_OUTPUT still
    # needs both keys present — an absent key is a different failure mode
    # (a step referencing it later errors instead of seeing an empty string).
    import subprocess

    result = tmp_path / "result.json"
    result.write_text(json.dumps({
        "leaderboard": {"entries": [{"key": "a", "status": "failed", "composite": None}]}
    }))
    script = ACTION_DIR / "extract_outputs.py"
    out = subprocess.run(
        [sys.executable, str(script), str(result)],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "composite=\n" in out
    assert "winner=\n" in out
