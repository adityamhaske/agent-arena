#!/usr/bin/env python3
"""Post or update the leaderboard as a pull request comment.

Stdlib only — urllib against the GitHub REST API — because this script ships
inside the arena's own repo and the engine it evaluates is stdlib-only too.
Adding requests or PyGithub here would be a strange place to break that rule.

Two JSON shapes are read, and they are not the same:

  --result    `arena evaluate --json` output: `leaderboard.entries[]`, keyed
              by `key`.
  --baseline  `arena export --format json` output: `rankings[]`, keyed by
              `model_key`.

Both are normalised to `{key: {status, composite}}` before comparing, so the
delta logic does not care which produced which.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

#: The comment is updated in place on every push, identified by this marker,
#: rather than growing a fresh comment per commit — the usual convention for
#: a bot comment that repeats on every push to a PR.
MARKER = "<!-- agent-arena-eval -->"


def _entries_from_result(path: str) -> dict[str, dict]:
    data = json.loads(open(path, encoding="utf-8").read())
    return {
        e["key"]: {"status": e.get("status"), "composite": e.get("composite")}
        for e in data.get("leaderboard", {}).get("entries", [])
    }


def _entries_from_baseline(path: str) -> dict[str, dict]:
    data = json.loads(open(path, encoding="utf-8").read())
    return {
        r["model_key"]: {"status": r.get("status"), "composite": r.get("composite")}
        for r in data.get("rankings", [])
    }


def render_table(current: dict[str, dict], baseline: dict[str, dict] | None) -> str:
    header = "| model | status | composite |" + (" delta |" if baseline else "")
    sep = "|---|---|---|" + ("---|" if baseline else "")
    rows = [header, sep]

    ranked = sorted(
        current.items(),
        key=lambda kv: (kv[1]["status"] != "ranked", -(kv[1]["composite"] or 0)),
    )
    for key, entry in ranked:
        composite = entry["composite"]
        cell = f"{composite:.3f}" if composite is not None else "—"
        row = f"| `{key}` | {entry['status']} | {cell} |"
        if baseline:
            before = baseline.get(key, {}).get("composite")
            if composite is None or before is None:
                row += " — |"
            else:
                delta = composite - before
                arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "·")
                row += f" {arrow} {delta:+.3f} |"
        rows.append(row)

    if baseline:
        new_keys = set(current) - set(baseline)
        gone_keys = set(baseline) - set(current)
        if new_keys:
            rows.append("")
            rows.append(f"New this run: {', '.join(sorted(new_keys))}")
        if gone_keys:
            rows.append(f"No longer present: {', '.join(sorted(gone_keys))}")

    return "\n".join(rows)


def _api(method: str, url: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8") or "{}")


def upsert_comment(repo: str, pr: int, token: str, body: str) -> None:
    body = f"{MARKER}\n{body}"
    base = f"https://api.github.com/repos/{repo}/issues/{pr}/comments"

    comments = _api("GET", base, token)
    existing = next((c for c in comments if MARKER in c.get("body", "")), None)

    if existing:
        patch_url = f"https://api.github.com/repos/{repo}/issues/comments/{existing['id']}"
        _api("PATCH", patch_url, token, {"body": body})
    else:
        _api("POST", base, token, {"body": body})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", required=True)
    parser.add_argument("--baseline", default="")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    args = parser.parse_args()

    current = _entries_from_result(args.result)
    baseline = _entries_from_baseline(args.baseline) if args.baseline else None

    table = render_table(current, baseline)
    heading = "## Agent Arena result" if not baseline else "## Agent Arena result (vs base branch)"
    body = f"{heading}\n\n{table}"

    token = os.environ.get("GH_TOKEN")
    if not token:
        print("GH_TOKEN not set; printing the comment instead of posting it:\n")
        print(body)
        return 0

    try:
        upsert_comment(args.repo, args.pr, token, body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        print(f"Could not post the PR comment: HTTP {exc.code}: {detail}", file=sys.stderr)
        print("The evaluation itself still succeeded; only the comment failed.", file=sys.stderr)
        return 0  # never fail the whole job over a comment
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
