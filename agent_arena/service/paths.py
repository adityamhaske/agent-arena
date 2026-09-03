"""Turning a caller-supplied name into a path you can safely act on.

Project names and run ids arrive from an HTTP request and from a command line.
Both are untrusted input, and both end up in a path that something is about to
delete. ``resolve_within`` is the one place that check lives, so it cannot be
half-implemented in one caller and forgotten in another.
"""

from __future__ import annotations

from pathlib import Path

from .errors import ServiceError

#: Names we are willing to build a path from. Deliberately narrower than the
#: filesystem allows: a project called ``../etc`` is never worth supporting.
_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")


def safe_name(name: str, what: str = "name") -> str:
    """Reject anything that is not a single, ordinary path segment."""
    text = str(name or "").strip()
    if not text:
        raise ServiceError(f"a {what} is required")
    if text in (".", "..") or "/" in text or "\\" in text:
        raise ServiceError(
            f"{what} {text!r} is not a single folder name. "
            "Use just the name, not a path."
        )
    bad = sorted(set(text) - _SAFE)
    if bad:
        raise ServiceError(
            f"{what} {text!r} contains {''.join(bad)!r}; "
            "use letters, digits, dashes, underscores and dots only"
        )
    return text


def resolve_within(root: str | Path, name: str, what: str = "name") -> Path:
    """The path ``name`` names inside ``root``, proven to actually be inside it.

    Both sides are resolved before comparison, so a symlink pointing out of the
    directory is caught as well as a traversing name.
    """
    safe = safe_name(name, what)
    base = Path(root).resolve()
    target = (base / safe).resolve()
    if target != base and base not in target.parents:
        raise ServiceError(f"{what} {name!r} resolves outside {base}")
    return target


def directory_size(path: Path) -> int:
    """Bytes under ``path``. Used to tell a caller what a delete would reclaim."""
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:  # noqa: PERF203 — a vanished file is not an error here
                pass
    return total
