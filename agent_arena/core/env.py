"""Reading API keys out of a ``.env`` file.

Credentials reach the arena through ``os.environ`` and nowhere else. That is
fine in a shell that has sourced a profile, and wrong everywhere else: started
from a desktop icon, from an IDE's run button, or from a cron entry, the
process inherits none of those exports. :meth:`ArenaRunner.preflight` then
skips every real model for "missing credentials" and the run finishes having
measured nothing — the worst failure mode a tool has, because it still looks
like a success.

This module closes that gap without adding a dependency: the engine is
stdlib-only, so there is no ``python-dotenv`` here, just a parser. It is
self-contained on purpose — text in, environment out — so the caller decides
when loading happens and what to tell the user about it.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

#: Where a machine-wide ``.env`` lives, relative to the user's home directory.
USER_ENV_FILE = Path(".config") / "agent-arena" / ".env"

ENV_BASENAME = ".env"

# Only names the shell itself could have exported. A line like `2FA=x` is a
# typo or a fragment of something else, never a variable this process can use.
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Expanded inside double quotes only. An unlisted escape is left alone so a
# Windows path — "C:\Users\me" — survives the round trip unmangled.
_DOUBLE_QUOTE_ESCAPES = {
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "\\": "\\",
    '"': '"',
    "'": "'",
}


def parse_env(text: str) -> dict[str, str]:
    """Parse ``.env`` text into a mapping, skipping anything malformed.

    A stray line must never stop an evaluation, so this parser has no error
    path: a line it cannot understand is dropped and the rest of the file is
    still read. The alternative — refusing to start because line 9 has a typo
    — costs the user their run to protect them from nothing.

    It follows the shell conventions the format borrows from, because getting
    them backwards corrupts a key silently rather than loudly:

    * ``KEY=value``, with an optional ``export`` prefix
    * ``#`` starts a comment on its own line, or after a value where it
      follows whitespace — so a key that contains a literal ``#`` survives
    * double quotes expand ``\\n``, ``\\t``, ``\\"``, ``\\\\``; single quotes
      keep every character literally
    * an unquoted value is stripped of surrounding whitespace; a quoted one
      keeps what is inside the quotes
    """
    values: dict[str, str] = {}
    for line in text.splitlines():
        parsed = _parse_line(line)
        if parsed is not None:
            key, value = parsed
            values[key] = value  # a repeated key means the later line wins
    return values


def find_env_files(start: str | Path | None = None) -> list[Path]:
    """List the ``.env`` files that exist, ordered so the nearest one is last.

    Two locations, no directory walk: ``~/.config/agent-arena/.env`` holds the
    keys that are true for every project on the machine, and ``<project>/.env``
    holds the ones that are true for this one. Returning them nearest-last lets
    a caller apply them in order and let the specific override the general.

    Files that do not exist are left out rather than returned as candidates,
    so a caller can report exactly which files it read.
    """
    if start is None:
        start = Path.cwd()
    project_dir = Path(start)
    if project_dir.is_file():
        # Callers hold a path to config.yaml as often as to the folder itself.
        project_dir = project_dir.parent

    candidates = [Path.home() / USER_ENV_FILE, project_dir / ENV_BASENAME]
    return [path for path in candidates if path.is_file()]


def load_env(start: str | Path | None = None, override: bool = False) -> dict[str, str]:
    """Populate ``os.environ`` from the ``.env`` files near ``start``.

    With ``override=False`` (the default) a variable already present in the
    real environment wins over every file. An explicitly exported key is the
    user's most deliberate statement of intent, and it must beat a ``.env``
    that has been sitting in the repo since a rotated key was still valid.
    ``override=True`` inverts that, for the caller who wants the file to be
    the source of truth.

    Returns only the variables it actually set, so the caller can tell the
    user what changed — "loaded ANTHROPIC_API_KEY from .env" — instead of
    leaving credentials appearing from nowhere.
    """
    merged: dict[str, str] = {}
    for path in find_env_files(start):
        merged.update(parse_env(_read_text(path)))

    applied: dict[str, str] = {}
    for key, value in merged.items():
        if not override and key in os.environ:
            continue
        os.environ[key] = value
        applied[key] = value
    return applied


def _read_text(path: Path) -> str:
    """Read a file, treating an unreadable one as empty.

    Same reasoning as a malformed line: a ``.env`` with the wrong permissions
    or a stray byte is a reason to fall back to the real environment, not a
    reason to end the run.
    """
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _parse_line(line: str) -> tuple[str, str] | None:
    """Return ``(key, value)`` for one line, or ``None`` if it is not one."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    if stripped.startswith("export") and stripped[6:7].isspace():
        stripped = stripped[6:].lstrip()

    key, sep, rest = stripped.partition("=")
    if not sep:
        return None
    key = key.strip()
    if not _KEY_RE.match(key):
        return None

    value = _parse_value(rest.strip())
    if value is None:
        return None
    return key, value


def _parse_value(raw: str) -> str | None:
    """Unquote and de-comment one value, or ``None`` if it is malformed."""
    quote = raw[:1]
    if quote not in ('"', "'"):
        return _strip_comment(raw).rstrip()

    chars: list[str] = []
    index = 1
    while index < len(raw):
        char = raw[index]
        if char == "\\" and quote == '"' and index + 1 < len(raw):
            following = raw[index + 1]
            chars.append(_DOUBLE_QUOTE_ESCAPES.get(following, "\\" + following))
            index += 2
            continue
        if char == quote:
            trailing = raw[index + 1 :].lstrip()
            if trailing and not trailing.startswith("#"):
                return None  # `KEY="a" junk` — we cannot guess what was meant
            return "".join(chars)
        chars.append(char)
        index += 1
    return None  # unterminated quote


def _strip_comment(value: str) -> str:
    """Cut an unquoted value at a ``#`` that starts a comment.

    A ``#`` only opens a comment when whitespace precedes it. Secrets contain
    ``#`` often enough that truncating ``sk-ab#cd`` at the hash would hand the
    provider a subtly wrong key and an authentication error to debug.
    """
    for index, char in enumerate(value):
        if char == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index]
    return value
