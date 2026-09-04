"""Agent Arena target: the Multi-Agent Research Assistant, run in-process.

The assistant is a four-agent LangGraph pipeline (planner → executor → critic →
synthesizer). This file is the entire contract between it and the arena: one
callable that takes a question and returns the report, the spend, and a couple
of numbers about how the run went. Everything downstream — scorers, weights,
constraints, the leaderboard — is the machinery that already grades models.

Why in-process rather than over the HTTP API: the engine ships a local host
(`research_engine.local`) with a SQLite checkpointer and an in-memory event
sink, so the full pipeline runs with no Docker, no Postgres, no Redis and no
login. Fewer moving parts between the arena and the thing being measured.

Where the assistant lives is read from `MARA_BACKEND`, falling back to the
sibling checkout beside this repository.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

#: …/projects/<name>/pipelines/mara.py → …/Documents/projects
_SIBLINGS = Path(__file__).resolve().parents[4]
BACKEND = Path(os.environ.get("MARA_BACKEND") or _SIBLINGS / "Multi-Agent Research Assistant" / "backend")

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


async def _drive(query: str, depth: str, fake: bool, data_dir: Path):
    """One research session, start to finish. Mirrors `research_engine.cli._drive`."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from research_engine.local import (
        InProcessEventSink,
        SqliteCache,
        load_env_file,
        run_config_from_env,
    )
    from research_engine.runner import resume, run

    # The CLI's default is relative to its own cwd; ours has to be explicit.
    load_env_file(BACKEND.parent / ".env")

    try:
        run_config = run_config_from_env(fake=fake)
    except SystemExit as exc:  # "no provider key" — a message, not a crash
        raise RuntimeError(str(exc)) from exc

    ports = {
        "event_sink": InProcessEventSink(on_event=None),
        "cache": SqliteCache(data_dir / "cache.sqlite"),
        "run_config": run_config,
    }

    async with AsyncSqliteSaver.from_conn_string(str(data_dir / "checkpoints.sqlite")) as saver:
        await saver.setup()
        session_id = f"arena-{uuid.uuid4().hex[:12]}"
        outcome = await run(
            checkpointer=saver,
            session_id=session_id,
            user_id="arena",
            query=query,
            depth=depth,
            **ports,
        )
        # The review gate is a human in the product and nobody here; approving
        # resumes from the checkpoint rather than replanning, so the report we
        # grade is the finalized one.
        if outcome.status == "awaiting_approval":
            outcome = await resume(
                checkpointer=saver, session_id=session_id, approved=True, **ports
            )
        return outcome


async def research(prompt, params=None, **ctx):
    """The target. `params` comes from the `params:` block of each config entry.

    Declared `async` because the engine is: the arena awaits a coroutine target
    directly, so nothing here has to wrap an event loop around it.
    """
    params = params or {}
    depth = str(params.get("depth", "balanced"))
    fake = bool(params.get("fake", True))

    started = time.perf_counter()
    # A fresh directory per call: SQLite under concurrency is the wrong thing to
    # debug mid-sweep, and a shared search cache would let an early test case
    # subsidise a later one — which is exactly the unfairness the arena exists
    # to avoid.
    with tempfile.TemporaryDirectory(prefix="arena-mara-") as tmp:
        outcome = await _drive(prompt, depth, fake, Path(tmp))
    measured_ms = (time.perf_counter() - started) * 1000.0

    if outcome.error:
        raise RuntimeError(f"engine failed ({outcome.status}): {outcome.error}")

    return {
        "output": outcome.report or "",
        # The engine counts its own four agents' spend; the price catalog sees
        # one opaque call, so these are the numbers to trust.
        "cost_usd": outcome.cost_usd,
        "input_tokens": outcome.tokens_input,
        "output_tokens": outcome.tokens_output,
        "latency_ms": (outcome.elapsed_seconds or 0) * 1000.0 or measured_ms,
        "metrics": {
            "sources": float(len(outcome.sources)),
            "rework_loops": float(outcome.rework_count),
        },
    }
