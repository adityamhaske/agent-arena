"""The lifecycle of a run: list, label, archive, delete, reclaim.

Before this existed a run could be created and read and nothing else. The
database grew forever, and the only way to remove anything was to delete the
whole sqlite file — which took every other run with it.

Every destructive function here takes ``dry_run`` and returns the same plan
either way. That is not a convenience: the plan *is* what a confirmation
dialog shows, so if the two could diverge the dialog would be lying about
what is about to happen.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ..core.config import ProjectConfig, load_config
from ..core.store import ResultStore, utcnow
from .errors import NotFoundError, ServiceError
from .paths import directory_size, resolve_within, safe_name


def _config(projects_dir: str | Path, project: str) -> ProjectConfig:
    root = resolve_within(projects_dir, project, "project name")
    if not root.is_dir():
        raise NotFoundError(f"no project named {project!r} in {Path(projects_dir).resolve()}")
    return load_config(root)


def _store(config: ProjectConfig) -> ResultStore:
    if not config.database.exists():
        raise NotFoundError(
            f"{config.project!r} has no results database yet — run "
            f"`arena evaluate --project {config.root}` first"
        )
    return ResultStore(config.database)


def list_runs(
    projects_dir: str | Path,
    project: str,
    *,
    limit: int = 50,
    include_deleted: bool = False,
    include_archived: bool = True,
) -> list[dict[str, Any]]:
    """Past runs, newest first. Soft-deleted ones are hidden unless asked for."""
    config = _config(projects_dir, project)
    if not config.database.exists():
        return []
    with ResultStore(config.database) as store:
        return store.runs(
            project=config.project,
            limit=limit,
            include_deleted=include_deleted,
            include_archived=include_archived,
        )


def get_run(projects_dir: str | Path, project: str, run_id: str) -> dict[str, Any]:
    """One run with its rankings attached."""
    config = _config(projects_dir, project)
    with _store(config) as store:
        row = store.run(run_id)
        if row is None:
            raise NotFoundError(f"no run {run_id!r} in project {project!r}")
        row["rankings"] = store.rankings(run_id)
    return row


def label_run(
    projects_dir: str | Path,
    project: str,
    run_id: str,
    *,
    label: str | None = None,
    notes: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Give a run a human name, so it is not only ``run_20260903_175823_38dd9f``."""
    config = _config(projects_dir, project)
    fields: dict[str, Any] = {}
    if label is not None:
        fields["label"] = label
    if notes is not None:
        fields["notes_json"] = json.dumps({"notes": notes})
    if tags is not None:
        fields["tags"] = ",".join(str(tag).strip() for tag in tags if str(tag).strip())
    if not fields:
        raise ServiceError("give at least one of label, notes or tags")
    with _store(config) as store:
        if store.run(run_id) is None:
            raise NotFoundError(f"no run {run_id!r} in project {project!r}")
        store.set_run_flags(run_id, **fields)
        return store.run(run_id) or {}


def archive_run(
    projects_dir: str | Path, project: str, run_id: str, archived: bool = True
) -> dict[str, Any]:
    """Hide a run from the default listing without destroying it.

    Deliberately distinct from delete. "I do not want to see this any more" is
    usually what someone means, and offering only deletion pushes them into an
    irreversible action to get a reversible outcome.
    """
    config = _config(projects_dir, project)
    with _store(config) as store:
        if store.run(run_id) is None:
            raise NotFoundError(f"no run {run_id!r} in project {project!r}")
        store.set_run_flags(run_id, archived_at=utcnow() if archived else None)
        return store.run(run_id) or {}


def delete_run(
    projects_dir: str | Path,
    project: str,
    run_id: str,
    *,
    hard: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove a run and its report files.

    Soft by default: the rows are hidden and recoverable until ``vacuum``.
    ``hard=True`` removes them outright, cascading to results and rankings.
    """
    config = _config(projects_dir, project)
    safe_name(run_id, "run id")
    with _store(config) as store:
        row = store.run(run_id, include_deleted=True)
        if row is None:
            raise NotFoundError(f"no run {run_id!r} in project {project!r}")

        report_dir = resolve_within(config.results_dir, run_id, "run id")
        report_files = (
            [str(p) for p in sorted(report_dir.rglob("*")) if p.is_file()]
            if report_dir.is_dir()
            else []
        )
        plan = {
            "run_id": run_id,
            "project": config.project,
            "deleted": False,
            "hard": hard,
            "results_removed": row.get("n_results") or 0,
            "report_files": report_files,
            "bytes": directory_size(report_dir),
            "dry_run": dry_run,
        }
        if dry_run:
            return plan

        outcome = store.delete_run(run_id, hard=hard)
        plan["deleted"] = outcome["deleted"]
        plan["results_removed"] = outcome["results_removed"] or plan["results_removed"]

    if report_dir.is_dir():
        shutil.rmtree(report_dir)
    return plan


def restore_run(projects_dir: str | Path, project: str, run_id: str) -> dict[str, Any]:
    """Undo a soft delete. The report files are gone; the measurements are not."""
    config = _config(projects_dir, project)
    with _store(config) as store:
        if store.run(run_id, include_deleted=True) is None:
            raise NotFoundError(f"no run {run_id!r} in project {project!r}")
        store.set_run_flags(run_id, deleted_at=None)
        return store.run(run_id) or {}


def vacuum(
    projects_dir: str | Path, project: str, *, dry_run: bool = False
) -> dict[str, Any]:
    """Hard-delete every soft-deleted run and reclaim the space."""
    config = _config(projects_dir, project)
    with _store(config) as store:
        return store.vacuum(project=config.project, dry_run=dry_run)
