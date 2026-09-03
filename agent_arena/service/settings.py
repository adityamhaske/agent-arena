"""User-level preferences, the ones that outlive a single project.

Everything the arena knows today is either a per-project ``config.yaml`` or a
command-line flag, so there is nowhere to put "I always want the dark theme",
"my projects live in ``~/work/evals``", or a saved provider profile. ``arena
ui`` therefore forgets every choice the moment it exits.

The line this module draws matters: a **project** is a folder and its settings
stay in that folder (that is invariant 5, and nothing here weakens it). This
file is for the preferences that span projects and belong to the person, not to
any one evaluation. If a value changes what a run measures, it belongs in the
project. If it changes how the tool behaves for *you*, it belongs here.

The file is JSON at ``$XDG_CONFIG_HOME/agent-arena/settings.json``, written
whole and atomically, chmod 0600 because saved provider profiles live in it.
Two things it deliberately refuses to do: lock you out of your own tool because
a byte got mangled (a corrupt file is quarantined, not fatal), and accept a
misspelled key in silence.
"""

from __future__ import annotations

import copy
import difflib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .errors import ServiceError

#: Every user preference, with the value used when the file says nothing. The
#: run/generation numbers mirror :class:`agent_arena.core.config.RunSettings`
#: and the example projects, so a project scaffolded from these settings
#: behaves the same as one written by hand.
DEFAULTS: dict[str, Any] = {
    "projects_dir": "projects",  # where `arena ui` looks for project folders
    "theme": "system",  # system|light|dark
    "density": "comfortable",  # comfortable|compact — table and card padding
    "open_browser": True,  # `arena ui` opens a browser window on launch
    "default_landing": "overview",  # overview|projects|runs — first page after launch
    "number_format": "comma",  # comma|space|none — thousands separator in the UI
    "currency": "USD",  # display only; sourced prices are USD and are not converted
    "timezone": "local",  # "local" or an IANA name like "Europe/Berlin"
    # Seeds for newly created projects. These are starting points a project may
    # override; once written into a config.yaml the project owns them.
    "defaults": {
        "trials": 1,  # repeats per test case
        "concurrency": 4,  # in-flight model calls
        "timeout_s": 120.0,  # per-call ceiling
        "retries": 2,  # retries after a retryable provider failure
        "temperature": 0,  # evaluations want determinism, not variety
        "max_tokens": 512,  # matches the CLI's cost-forecast fallback
    },
    # Spend caps. None means "no cap": a ceiling nobody chose is a guess, and a
    # guessed ceiling stops runs for no reason.
    "budgets": {
        "max_run_usd": None,  # abort a run projected to cost more than this
        "max_model_usd": None,  # same, per model within a run
        "confirm_above_usd": 5.0,  # ask before starting a run forecast above this
        "on_exceed": "stop",  # stop|warn — what to do when a cap is hit
    },
    "providers": [],  # saved ProviderSpec dicts; service/providers.py owns their shape
    "update_check": True,  # check PyPI for a newer arena on launch
    "log_level": "warning",  # debug|info|warning|error
}

#: Appended to the settings file when it cannot be parsed. One fixed name, so
#: there is exactly one place to look for what was rescued.
CORRUPT_SUFFIX = ".corrupt"


def config_dir() -> Path:
    """Where user settings live.

    ``XDG_CONFIG_HOME`` is read on every call rather than at import time, which
    is what lets a test or a sandbox redirect the whole store by setting one
    environment variable.
    """
    override = os.environ.get("XDG_CONFIG_HOME")
    base = Path(override) if override else Path.home() / ".config"
    return base / "agent-arena"


def settings_path() -> Path:
    return config_dir() / "settings.json"


def load() -> dict[str, Any]:
    """Return the defaults with the saved file merged over them.

    Never raises. A missing file is the normal first-run case, and a corrupt
    file is quarantined rather than reported: being unable to start the tool
    because one byte of JSON went bad is a worse failure than losing a
    preference.
    """
    path = settings_path()
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return copy.deepcopy(DEFAULTS)
    except (OSError, ValueError):
        _quarantine(path)
        return copy.deepcopy(DEFAULTS)

    if not isinstance(stored, dict):
        # A list or a bare string parses as JSON but is not a settings file.
        _quarantine(path)
        return copy.deepcopy(DEFAULTS)

    # Unknown keys in the file are kept, not dropped: a file written by a newer
    # arena must survive being read by an older one. `save` is where a typo is
    # caught, because there a human is making the mistake right now.
    return _deep_merge(DEFAULTS, stored)


def save(patch: dict[str, Any]) -> dict[str, Any]:
    """Merge ``patch`` into the saved settings and return the whole result.

    The merge is deep, so ``{"budgets": {"on_exceed": "warn"}}`` leaves the
    other budget keys alone. Lists — ``providers`` above all — are replaced
    whole; there is no sane element-wise merge for them.
    """
    if not isinstance(patch, dict):
        raise ServiceError(
            f"settings patch must be a mapping of key to value, got {type(patch).__name__}"
        )
    _reject_unknown(patch.keys())

    merged = _deep_merge(load(), patch)
    _write(merged)
    return merged


def reset(keys: Iterable[str] | str | None = None) -> dict[str, Any]:
    """Restore ``keys`` to their defaults, or every key when ``None``.

    Resetting replaces a key outright instead of merging into it, which is the
    only way to clear a nested value that a patch put there.
    """
    if keys is None:
        # Deleting beats writing DEFAULTS back: with no file, a later arena
        # release's better default is picked up instead of being pinned to
        # whatever today's default happened to be.
        path = settings_path()
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return copy.deepcopy(DEFAULTS)

    names = [keys] if isinstance(keys, str) else list(keys)
    _reject_unknown(names)

    current = load()
    for name in names:
        current[name] = copy.deepcopy(DEFAULTS[name])
    _write(current)
    return current


# ---- internals ------------------------------------------------------------


def _reject_unknown(keys: Iterable[str]) -> None:
    """A key that is not a setting is a typo, and a typo that saves quietly is
    a preference the user believes they set and never get."""
    valid = sorted(DEFAULTS)
    for key in keys:
        if key in DEFAULTS:
            continue
        close = difflib.get_close_matches(str(key), valid, n=1)
        hint = f" Did you mean {close[0]!r}?" if close else ""
        raise ServiceError(
            f"{key!r} is not a setting.{hint} Valid keys: {', '.join(valid)}"
        )


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in patch.items():
        existing = merged.get(key)
        if isinstance(value, dict) and isinstance(existing, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _quarantine(path: Path) -> None:
    """Move an unreadable settings file aside instead of overwriting it.

    Whatever is in there was typed by a person; the next `save` would destroy
    it. Renaming costs nothing and keeps the hand-edited version recoverable.
    """
    try:
        os.replace(path, path.with_name(path.name + CORRUPT_SUFFIX))
    except OSError:
        # Unreadable *and* unmovable — a read-only config dir, say. Returning
        # defaults still beats refusing to start.
        pass


def _write(data: dict[str, Any]) -> None:
    """Replace the settings file in one step, at mode 0600."""
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"

    # The temp file goes in the destination directory so os.replace is a rename
    # within one filesystem, which is atomic: a crash mid-write leaves either
    # the old settings or the new ones, never half of either.
    handle, name = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=str(path.parent))
    tmp = Path(name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, 0o600)  # saved provider profiles make this file worth protecting
        os.replace(tmp, path)
    except BaseException:
        # A failed write must not leave a stray .tmp beside the real settings.
        tmp.unlink(missing_ok=True)
        raise
