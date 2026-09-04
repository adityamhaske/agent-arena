#!/usr/bin/env python3
"""Print `composite=`/`winner=` lines for $GITHUB_OUTPUT.

A separate file rather than a heredoc inline in action.yml: a heredoc's body
must sit at column 0 to satisfy bash, and that conflicts with YAML's
block-scalar indentation rules — mixing the two silently broke the workflow's
own syntax, which is the failure mode this file exists to avoid.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    with open(sys.argv[1], encoding="utf-8") as handle:
        data = json.load(handle)
    entries = data.get("leaderboard", {}).get("entries", [])
    ranked = [e for e in entries if e.get("status") == "ranked"]
    winner = ranked[0] if ranked else None
    print(f"composite={winner['composite']:.4f}" if winner else "composite=")
    print(f"winner={winner['key']}" if winner else "winner=")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
