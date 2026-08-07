"""Durable, queryable results.

Every call the arena makes is written to SQLite along with the run that
produced it, so you can answer questions no single report can: *did
claude-opus-5 get better on this project after the last model release? which
test has been flaky for three runs? what did we spend evaluating this month?*

One database per project by default (``results/arena.sqlite``); point several
projects at one shared file if you would rather query across them.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    project       TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL DEFAULT 'running',
    arena_version TEXT,
    git_sha       TEXT,
    label         TEXT,
    n_models      INTEGER,
    n_tests       INTEGER,
    n_results     INTEGER,
    winner        TEXT,
    total_cost_usd REAL,
    weights_json  TEXT,
    models_json   TEXT,
    config_json   TEXT,
    notes_json    TEXT
);

CREATE TABLE IF NOT EXISTS results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL REFERENCES runs(run_id),
    project       TEXT NOT NULL,
    model_key     TEXT NOT NULL,
    model         TEXT NOT NULL,
    provider      TEXT,
    test_id       TEXT NOT NULL,
    trial         INTEGER NOT NULL DEFAULT 1,
    eval_type     TEXT,
    status        TEXT NOT NULL,
    score         REAL,
    passed        INTEGER,
    output        TEXT,
    reference     TEXT,
    reason        TEXT,
    latency_ms    REAL,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL,
    attempts      INTEGER,
    error         TEXT,
    tags          TEXT,
    metrics_json  TEXT,
    detail_json   TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rankings (
    run_id       TEXT NOT NULL REFERENCES runs(run_id),
    project      TEXT NOT NULL,
    model_key    TEXT NOT NULL,
    model        TEXT NOT NULL,
    rank         INTEGER,
    status       TEXT,
    composite    REAL,
    metrics_json TEXT,
    stats_json   TEXT,
    failures     TEXT,
    warnings     TEXT,
    PRIMARY KEY (run_id, model_key)
);

CREATE INDEX IF NOT EXISTS idx_results_run    ON results(run_id);
CREATE INDEX IF NOT EXISTS idx_results_model  ON results(project, model_key);
CREATE INDEX IF NOT EXISTS idx_results_test   ON results(project, test_id);
CREATE INDEX IF NOT EXISTS idx_runs_project   ON runs(project, started_at);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResultStore:
    """Thin SQLite wrapper. Safe to share across the runner's worker threads."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._conn.commit()

    # ---- lifecycle ----------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> ResultStore:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # ---- writes -------------------------------------------------------

    def start_run(
        self,
        project: str,
        *,
        models: Sequence[str],
        n_tests: int,
        weights: dict[str, float],
        config_snapshot: dict[str, Any] | None = None,
        arena_version: str = "",
        git_sha: str = "",
        label: str = "",
    ) -> str:
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        with self._lock:
            self._conn.execute(
                """INSERT INTO runs
                   (run_id, project, started_at, status, arena_version, git_sha, label,
                    n_models, n_tests, weights_json, models_json, config_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    project,
                    utcnow(),
                    "running",
                    arena_version,
                    git_sha,
                    label,
                    len(models),
                    n_tests,
                    _dumps(weights),
                    _dumps(list(models)),
                    _dumps(config_snapshot or {}),
                ),
            )
            self._conn.commit()
        return run_id

    def record_result(self, run_id: str, project: str, result: Any) -> None:
        self.record_results(run_id, project, [result])

    def record_results(self, run_id: str, project: str, results: Iterable[Any]) -> None:
        rows = [
            (
                run_id,
                project,
                r.model_key,
                r.model,
                r.provider,
                r.test_id,
                r.trial,
                r.eval_type,
                r.status,
                r.score,
                None if r.passed is None else int(bool(r.passed)),
                _truncate(r.output),
                _truncate(_stringify(r.reference)),
                _truncate(r.reason, 1000),
                r.latency_ms,
                r.input_tokens,
                r.output_tokens,
                r.cost_usd,
                r.attempts,
                _truncate(r.error, 2000),
                ",".join(r.tags or []),
                _dumps(r.metrics or {}),
                _dumps(r.detail or {}),
                utcnow(),
            )
            for r in results
        ]
        if not rows:
            return
        with self._lock:
            self._conn.executemany(
                """INSERT INTO results
                   (run_id, project, model_key, model, provider, test_id, trial, eval_type,
                    status, score, passed, output, reference, reason, latency_ms,
                    input_tokens, output_tokens, cost_usd, attempts, error, tags,
                    metrics_json, detail_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
            self._conn.commit()

    def finish_run(
        self,
        run_id: str,
        project: str,
        leaderboard: Any,
        *,
        status: str = "completed",
        n_results: int = 0,
        total_cost_usd: float | None = None,
    ) -> None:
        winner = leaderboard.winner.key if getattr(leaderboard, "winner", None) else None
        with self._lock:
            self._conn.execute(
                """UPDATE runs
                   SET finished_at = ?, status = ?, n_results = ?, winner = ?,
                       total_cost_usd = ?, notes_json = ?
                   WHERE run_id = ?""",
                (
                    utcnow(),
                    status,
                    n_results,
                    winner,
                    total_cost_usd,
                    _dumps(getattr(leaderboard, "notes", [])),
                    run_id,
                ),
            )
            self._conn.executemany(
                """INSERT OR REPLACE INTO rankings
                   (run_id, project, model_key, model, rank, status, composite,
                    metrics_json, stats_json, failures, warnings)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        run_id,
                        project,
                        entry.key,
                        entry.model,
                        entry.rank,
                        entry.status,
                        entry.composite,
                        _dumps(
                            {
                                name: {"raw": m.raw, "normalized": m.normalized, "weight": m.weight}
                                for name, m in entry.metrics.items()
                            }
                        ),
                        _dumps(entry.stats),
                        _dumps(entry.failures),
                        _dumps(entry.warnings),
                    )
                    for entry in getattr(leaderboard, "entries", [])
                ],
            )
            self._conn.commit()

    # ---- reads --------------------------------------------------------

    def runs(self, project: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        query = "SELECT * FROM runs"
        params: list[Any] = []
        if project:
            query += " WHERE project = ?"
            params.append(project)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def run(self, run_id: str) -> dict[str, Any] | None:
        """One run by id, regardless of how far back it is."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return dict(row) if row else None

    def rankings(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM rankings WHERE run_id = ? ORDER BY rank IS NULL, rank",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def results(
        self,
        run_id: str | None = None,
        model_key: str | None = None,
        test_id: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        clauses, params = [], []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if model_key:
            clauses.append("model_key = ?")
            params.append(model_key)
        if test_id:
            clauses.append("test_id = ?")
            params.append(test_id)
        query = "SELECT * FROM results"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def model_history(
        self, project: str, model_key: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Composite and accuracy for one model across runs — regression tracking."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT r.run_id, r.started_at, k.rank, k.composite, k.status, k.metrics_json
                   FROM rankings k JOIN runs r ON r.run_id = k.run_id
                   WHERE k.project = ? AND k.model_key = ?
                   ORDER BY r.started_at DESC LIMIT ?""",
                (project, model_key, limit),
            ).fetchall()
        history = []
        for row in rows:
            record = dict(row)
            metrics = json.loads(record.pop("metrics_json") or "{}")
            record["accuracy"] = (metrics.get("accuracy") or {}).get("raw")
            record["cost"] = (metrics.get("cost") or {}).get("raw")
            record["latency"] = (metrics.get("latency") or {}).get("raw")
            history.append(record)
        return history

    def flaky_tests(self, project: str, run_id: str | None = None) -> list[dict[str, Any]]:
        """Tests whose score varies *between trials of the same run*.

        Grouping is always scoped to a run. Comparing across runs would report
        a config change — a different prompt, a different temperature — as
        trial flakiness, which is a different problem with a different fix.
        """
        clauses = ["project = ?", "status = 'ok'"]
        params: list[Any] = [project]
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT run_id, test_id, model_key, COUNT(*) AS n,
                           AVG(score) AS mean_score,
                           MIN(score) AS min_score, MAX(score) AS max_score
                    FROM results WHERE {' AND '.join(clauses)}
                    GROUP BY run_id, test_id, model_key
                    HAVING n > 1 AND max_score > min_score
                    ORDER BY (max_score - min_score) DESC""",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def export_csv(self, run_id: str, path: str | Path) -> Path:
        import csv  # noqa: PLC0415 — only needed on export

        rows = self.results(run_id=run_id, limit=1_000_000)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            path.write_text("", encoding="utf-8")
            return path
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return path


def _dumps(value: Any) -> str:
    return json.dumps(value, default=str)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)


def _truncate(text: Any, limit: int = 20000) -> str:
    if text is None:
        return ""
    text = str(text)
    return text if len(text) <= limit else text[:limit] + f"… [{len(text) - limit} chars truncated]"
