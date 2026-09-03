"""Project lifecycle: list, describe, duplicate, archive, delete.

The verbs that never existed. Project *creation* still lives in
:mod:`agent_arena.web.api` — moving it is a larger refactor with its own test
surface — but the destructive and lifecycle operations belong here from the
start, because they are the ones both the CLI and the browser need and neither
had.

Everything destructive takes ``dry_run`` and returns the same plan either way,
and every caller-supplied name goes through :mod:`agent_arena.service.paths`
before anything touches the filesystem.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..core.config import CONFIG_BASENAMES, load_config
from ..core.errors import ArenaError
from ..core.store import ResultStore
from .errors import ConflictError, NotFoundError, ServiceError
from .paths import directory_size, resolve_within, safe_name

#: Never copied when duplicating. A results database carried into a copy would
#: attribute one project's run history to another, which is worse than the copy
#: simply starting empty.
_NEVER_COPY = ("results", "__pycache__", ".git", ".venv")


def _project_dir(projects_dir: str | Path, name: str) -> Path:
    root = resolve_within(projects_dir, name, "project name")
    if not root.is_dir():
        raise NotFoundError(
            f"no project named {name!r} in {Path(projects_dir).resolve()}"
        )
    return root


def _config_file(root: Path) -> Path | None:
    for basename in CONFIG_BASENAMES:
        candidate = root / basename
        if candidate.is_file():
            return candidate
    return None


def list_projects(
    projects_dir: str | Path, *, include_archived: bool = False
) -> list[dict[str, Any]]:
    """Every project folder, with enough detail to render a list.

    A project whose config will not parse is still listed, with its error —
    hiding it would leave someone staring at a folder the tool pretends is not
    there.
    """
    base = Path(projects_dir)
    if not base.is_dir():
        return []
    entries = []
    for root in sorted(p for p in base.iterdir() if p.is_dir()):
        if _config_file(root) is None:
            continue
        record: dict[str, Any] = {"name": root.name, "path": str(root)}
        try:
            config = load_config(root)
        except ArenaError as exc:
            record.update(project=root.name, error=str(exc), archived=False, models=0)
            entries.append(record)
            continue
        archived = bool(config.raw.get("archived"))
        if archived and not include_archived:
            continue
        record.update(
            project=config.project,
            description=config.description,
            archived=archived,
            models=len(config.models),
            runs=_run_count(config),
        )
        entries.append(record)
    return entries


def _run_count(config: Any) -> int:
    if not config.database.exists():
        return 0
    try:
        with ResultStore(config.database) as store:
            return len(store.runs(project=config.project, limit=10_000))
    except Exception:  # noqa: BLE001 — a listing must not die on one bad database
        return 0


def describe_project(projects_dir: str | Path, name: str) -> dict[str, Any]:
    """One project: its config, its models, and how many runs it has."""
    root = _project_dir(projects_dir, name)
    config = load_config(root)
    return {
        "name": root.name,
        "path": str(root),
        "project": config.project,
        "description": config.description,
        "archived": bool(config.raw.get("archived")),
        "models": [
            {"key": spec.key, "model": spec.model, "enabled": spec.enabled}
            for spec in config.models
        ],
        "providers": [profile.to_dict() for profile in config.providers],
        "runs": _run_count(config),
        "database": str(config.database),
    }


def archive_project(
    projects_dir: str | Path, name: str, archived: bool = True
) -> dict[str, Any]:
    """Set ``archived:`` in the config so the project leaves default listings."""
    root = _project_dir(projects_dir, name)
    path = _config_file(root)
    if path is None:
        raise NotFoundError(f"{name!r} has no config file")

    from ..core.loaders import load_structured  # noqa: PLC0415 — optional yaml

    data = load_structured(path)
    if archived:
        data["archived"] = True
    else:
        data.pop("archived", None)
    _write_structured(path, data)
    return describe_project(projects_dir, name)


def duplicate_project(
    projects_dir: str | Path, name: str, new_name: str
) -> dict[str, Any]:
    """Copy a project, excluding its results.

    The new config's ``project:`` field is rewritten, so the two stay
    distinguishable when they share a database.
    """
    source = _project_dir(projects_dir, name)
    target_name = safe_name(new_name, "new project name")
    target = resolve_within(projects_dir, target_name, "new project name")
    if target.exists():
        raise ConflictError(f"{target_name!r} already exists at {target}")

    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns(*_NEVER_COPY, "*.sqlite", "*.sqlite-*"),
    )
    path = _config_file(target)
    if path is not None:
        from ..core.loaders import load_structured  # noqa: PLC0415

        data = load_structured(path)
        data["project"] = target_name
        data.pop("archived", None)
        _write_structured(path, data)
    return describe_project(projects_dir, target_name)


def delete_project(
    projects_dir: str | Path,
    name: str,
    *,
    keep_results: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Delete a project folder.

    ``keep_results`` removes the config, tests and scorers but leaves
    ``results/`` intact — a rename gone wrong should not be able to destroy a
    year of run history.
    """
    root = _project_dir(projects_dir, name)
    results = root / "results"

    if keep_results:
        doomed = [p for p in sorted(root.iterdir()) if p.resolve() != results.resolve()]
    else:
        doomed = [root]

    runs_removed = 0
    if not keep_results:
        try:
            config = load_config(root)
            runs_removed = _run_count(config)
        except ArenaError:
            runs_removed = 0

    plan = {
        "name": root.name,
        "path": str(root),
        "deleted": False,
        "keep_results": keep_results,
        "paths": [str(p) for p in doomed],
        "runs_removed": runs_removed,
        "bytes": sum(directory_size(p) for p in doomed),
        "dry_run": dry_run,
    }
    if dry_run:
        return plan

    for path in doomed:
        # Re-prove containment immediately before unlinking. The check at the
        # top of the function is the important one, but a delete is the last
        # place to take a path's provenance on trust.
        resolved = path.resolve()
        if Path(projects_dir).resolve() not in resolved.parents:
            raise ServiceError(f"refusing to delete {resolved}, which is outside the projects folder")
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    plan["deleted"] = True
    return plan


def _write_structured(path: Path, data: Any) -> None:
    """Write back in the format the file already used."""
    import json  # noqa: PLC0415

    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml  # noqa: PLC0415 — optional, per invariant 1
        except ImportError:
            raise ServiceError(
                f"editing {path.name} needs PyYAML: pip install pyyaml "
                "(or use a JSON config)"
            ) from None
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    else:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
