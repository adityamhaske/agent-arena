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

SCHEMA_VERSION = 2

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


#: Version -> the statements that take a database to it. Never edit a shipped
#: entry; add a new version instead, or an upgraded database and a fresh one
#: stop agreeing about what the schema is.
_MIGRATIONS: dict[int, tuple[str, ...]] = {
    2: (
        # Soft delete, so removing a run is recoverable until `vacuum`.
        "ALTER TABLE runs ADD COLUMN deleted_at TEXT",
        "ALTER TABLE runs ADD COLUMN archived_at TEXT",
        "ALTER TABLE runs ADD COLUMN tags TEXT",
        "CREATE INDEX IF NOT EXISTS idx_runs_live ON runs(project, deleted_at, started_at)",
    ),
}


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
        self._migrate()
        self._conn.commit()

    # ---- migrations ---------------------------------------------------

    def _migrate(self) -> None:
        """Bring an existing database up to :data:`SCHEMA_VERSION`.

        Driven by sqlite's own ``user_version`` pragma, so it is idempotent and
        needs no table of its own. Steps are additive ``ALTER TABLE ADD COLUMN``
        statements, which sqlite applies without rewriting the table — a
        database from an earlier version keeps every row it had.
        """
        current = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if current >= SCHEMA_VERSION:
            return
        for version, statements in sorted(_MIGRATIONS.items()):
            if version <= current:
                continue
            for statement in statements:
                try:
                    self._conn.execute(statement)
                except sqlite3.OperationalError as exc:
                    # A column added by a newer arena that then rolled back
                    # leaves the column present but the version behind. That is
                    # recoverable; anything else is not.
                    if "duplicate column name" not in str(exc).lower():
                        raise
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

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

    def runs(
        self,
        project: str | None = None,
        limit: int = 20,
        include_deleted: bool = False,
        include_archived: bool = True,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if project:
            clauses.append("project = ?")
            params.append(project)
        if not include_deleted:
            clauses.append("deleted_at IS NULL")
        if not include_archived:
            clauses.append("archived_at IS NULL")
        query = "SELECT * FROM runs"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def run(self, run_id: str, include_deleted: bool = False) -> dict[str, Any] | None:
        """One run by id, regardless of how far back it is."""
        query = "SELECT * FROM runs WHERE run_id = ?"
        if not include_deleted:
            query += " AND deleted_at IS NULL"
        with self._lock:
            row = self._conn.execute(query, (run_id,)).fetchone()
        return dict(row) if row else None

    def rankings(self, run_id: str, include_deleted: bool = False) -> list[dict[str, Any]]:
        # Joined to runs rather than filtered on rankings alone: a soft-deleted
        # run must disappear from every read path, and missing one is the
        # classic way a "deleted" row reappears somewhere else in the product.
        query = "SELECT k.* FROM rankings k JOIN runs r ON r.run_id = k.run_id WHERE k.run_id = ?"
        if not include_deleted:
            query += " AND r.deleted_at IS NULL"
        query += " ORDER BY k.rank IS NULL, k.rank"
        with self._lock:
            rows = self._conn.execute(query, (run_id,)).fetchall()
        return [dict(row) for row in rows]

    def results(
        self,
        run_id: str | None = None,
        model_key: str | None = None,
        test_id: str | None = None,
        limit: int = 1000,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        clauses, params = [], []
        if run_id:
            clauses.append("e.run_id = ?")
            params.append(run_id)
        if model_key:
            clauses.append("e.model_key = ?")
            params.append(model_key)
        if test_id:
            clauses.append("e.test_id = ?")
            params.append(test_id)
        if not include_deleted:
            clauses.append("r.deleted_at IS NULL")
        query = "SELECT e.* FROM results e JOIN runs r ON r.run_id = e.run_id"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY e.id LIMIT ?"
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
                   WHERE k.project = ? AND k.model_key = ? AND r.deleted_at IS NULL
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
        clauses = ["e.project = ?", "e.status = 'ok'", "r.deleted_at IS NULL"]
        params: list[Any] = [project]
        if run_id:
            clauses.append("e.run_id = ?")
            params.append(run_id)
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT e.run_id, e.test_id, e.model_key, COUNT(*) AS n,
                           AVG(e.score) AS mean_score,
                           MIN(e.score) AS min_score, MAX(e.score) AS max_score
                    FROM results e JOIN runs r ON r.run_id = e.run_id
                    WHERE {' AND '.join(clauses)}
                    GROUP BY e.run_id, e.test_id, e.model_key
                    HAVING n > 1 AND max_score > min_score
                    ORDER BY (max_score - min_score) DESC""",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    # ---- lifecycle ----------------------------------------------------

    def set_run_flags(self, run_id: str, **fields: Any) -> bool:
        """Update the mutable columns on a run. Returns whether a row changed.

        Only the lifecycle columns are writable here. A run's measurements are
        immutable by design — editing what a model scored after the fact would
        make the history worthless as evidence.
        """
        allowed = {"label", "notes_json", "tags", "archived_at", "deleted_at"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(
                f"cannot set {', '.join(sorted(unknown))} on a run; "
                f"writable fields are {', '.join(sorted(allowed))}"
            )
        if not fields:
            return False
        assignments = ", ".join(f"{name} = ?" for name in fields)
        with self._lock:
            cursor = self._conn.execute(
                f"UPDATE runs SET {assignments} WHERE run_id = ?",
                (*fields.values(), run_id),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def delete_run(self, run_id: str, hard: bool = False) -> dict[str, Any]:
        """Remove a run. Soft by default, so it is recoverable until ``vacuum``.

        A hard delete cascades to ``results`` and ``rankings`` explicitly:
        sqlite does not enforce the foreign keys here unless the pragma is on,
        and leaving orphans would silently inflate every aggregate query.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT run_id FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return {"run_id": run_id, "deleted": False, "hard": hard, "results_removed": 0}
            if not hard:
                self._conn.execute(
                    "UPDATE runs SET deleted_at = ? WHERE run_id = ?", (utcnow(), run_id)
                )
                self._conn.commit()
                return {"run_id": run_id, "deleted": True, "hard": False, "results_removed": 0}
            removed = self._conn.execute(
                "SELECT COUNT(*) FROM results WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
            self._conn.execute("DELETE FROM rankings WHERE run_id = ?", (run_id,))
            self._conn.execute("DELETE FROM results  WHERE run_id = ?", (run_id,))
            self._conn.execute("DELETE FROM runs     WHERE run_id = ?", (run_id,))
            self._conn.commit()
        return {"run_id": run_id, "deleted": True, "hard": True, "results_removed": removed}

    def deleted_runs(self, project: str | None = None) -> list[dict[str, Any]]:
        """Soft-deleted runs still occupying space — what ``vacuum`` would reclaim."""
        query = "SELECT * FROM runs WHERE deleted_at IS NOT NULL"
        params: list[Any] = []
        if project:
            query += " AND project = ?"
            params.append(project)
        with self._lock:
            rows = self._conn.execute(query + " ORDER BY deleted_at", params).fetchall()
        return [dict(row) for row in rows]

    def vacuum(self, project: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        """Hard-delete every soft-deleted run, then reclaim the file space.

        ``dry_run`` reports exactly what would go without touching anything, so
        a caller can show the real number before asking for confirmation.
        """
        pending = self.deleted_runs(project)
        run_ids = [row["run_id"] for row in pending]
        plan = {
            "runs_removed": len(run_ids),
            "run_ids": run_ids,
            "results_removed": 0,
            "bytes_before": self.path.stat().st_size if self.path.exists() else 0,
            "bytes_after": None,
            "dry_run": dry_run,
        }
        if not run_ids:
            plan["bytes_after"] = plan["bytes_before"]
            return plan
        with self._lock:
            marks = ",".join("?" * len(run_ids))
            plan["results_removed"] = self._conn.execute(
                f"SELECT COUNT(*) FROM results WHERE run_id IN ({marks})", run_ids
            ).fetchone()[0]
        if dry_run:
            plan["bytes_after"] = plan["bytes_before"]
            return plan
        for run_id in run_ids:
            self.delete_run(run_id, hard=True)
        with self._lock:
            # VACUUM cannot run inside a transaction, and sqlite3 opens one
            # implicitly on write; commit first or this raises.
            self._conn.commit()
            self._conn.execute("VACUUM")
            self._conn.commit()
        plan["bytes_after"] = self.path.stat().st_size if self.path.exists() else 0
        return plan

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
