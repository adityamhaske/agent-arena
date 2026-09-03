"""Credentials: resolving a reference, and refusing to be printed.

These primitives live in ``core`` rather than ``service`` because the connector
registry needs them to resolve a provider profile's key, and ``service`` already
imports the registry — putting them the other way round would be a cycle *and*
would point the dependency arrow backwards.

:mod:`agent_arena.service.secrets` re-exports everything here and adds the
management side: the vendor-convention fallback, and keyring CRUD.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

from ..core.env import USER_ENV_FILE
from .errors import SecretError

#: What a credential looks like everywhere except :meth:`Secret.reveal`.
MASK = "***"

#: Values shorter than this are not redacted. A four-character "secret" is a
#: word before it is a credential, and blanking every occurrence of it would
#: mangle the very error message redaction exists to make safe.
MIN_REDACTABLE = 8

#: A resolver that hangs holds up the whole evaluation. ``op read`` waiting on
#: a biometric prompt that no one is there to answer is the realistic case.
COMMAND_TIMEOUT_S = 30

#: The store the arena keeps itself when the OS offers none. It sits beside the
#: machine-wide ``.env`` on purpose: one directory to audit, one to lock down.
FALLBACK_STORE = USER_ENV_FILE.parent / "secrets.json"

#: Reference schemes, in the order they are offered to a user who mistypes one.
SCHEMES = ("env", "keyring", "file", "cmd")

# A reference is the *whole* string. `Bearer ${env:TOKEN}` is not interpolated
# — half-substituting a credential into a larger string is a feature with its
# own escaping rules, and guessing at one would produce a subtly wrong key.
_REF_RE = re.compile(r"^\$\{(?P<scheme>[^:{}]*):(?P<body>.*)\}$", re.DOTALL)


class Secret:
    """A credential value that refuses to print itself.

    ``repr``, ``str``, ``format`` and therefore every f-string yield
    :data:`MASK`. That is not decoration: it is the difference between a
    logged request and a leaked key, and it is why this deliberately does
    **not** subclass ``str`` — inheriting ``str.__str__`` would hand the value
    straight back to the first ``"%s"`` that touched it.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value if isinstance(value, str) else str(value)

    def reveal(self) -> str:
        """The real value. The only way to get it, and greppable for review."""
        return self._value

    def __repr__(self) -> str:
        return MASK

    def __str__(self) -> str:
        return MASK

    def __bool__(self) -> bool:
        return bool(self._value)

    def __len__(self) -> int:
        # Useful for "the key is 12 characters, that cannot be right" without
        # revealing which twelve.
        return len(self._value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Secret):
            # Constant-time: comparing two secrets is rare, but a plain `==`
            # here would leak the shared prefix length through timing, and
            # writing the careful version costs nothing.
            return hmac.compare_digest(
                self._value.encode("utf-8"), other._value.encode("utf-8")
            )
        # Never equal to a bare string: `secret == "sk-123"` is code smuggling
        # a credential into a comparison, and it should not quietly work.
        return NotImplemented

    # Defining __eq__ drops __hash__, which suits a credential — it has no
    # business being a dict key, where a debugger would render it as one.
    __hash__ = None  # type: ignore[assignment]


def resolve(ref: Any, *, base_dir: str | Path | None = None) -> Secret | None:
    """Resolve one credential reference.

    ``${env:NAME}``, ``${keyring:service/account}``, ``${file:~/.secrets/key}``
    and ``${cmd:op read op://vault/item/field}`` are looked up; anything else
    is a literal value the user typed in directly.

    Returns ``None`` when the reference is well formed but names nothing — an
    unset variable, a file that is not there. The caller decides whether that
    is a problem, because for a local model it is not.

    Raises :class:`ServiceError` when the reference itself is wrong: an unknown
    scheme, a key file other users can read, a command that failed.
    """
    if ref is None:
        return None
    text = ref if isinstance(ref, str) else str(ref)
    if not text.strip():
        return None

    match = _REF_RE.match(text.strip())
    if match is None:
        return _wrap(text)  # a literal value, kept exactly as it was given

    scheme = match.group("scheme").strip().lower()
    body = match.group("body").strip()
    handler = _HANDLERS.get(scheme)
    if handler is None:
        supported = ", ".join("${%s:...}" % name for name in SCHEMES)
        raise SecretError(
            f"unknown secret scheme {scheme!r}. Use one of: {supported} "
            "— or paste the value itself, with no ${...} wrapper."
        )
    return handler(body, base_dir)


def redact(text: Any, secrets: Any) -> str:
    """Replace every revealed credential in ``text`` with :data:`MASK`.

    The last line of defence, for the error message that quotes the request it
    failed on. Values under :data:`MIN_REDACTABLE` characters are left alone;
    they are not real keys, and blanking them would corrupt the message.
    """
    result = text if isinstance(text, str) else str(text)
    if secrets is None:
        return result
    if isinstance(secrets, (Secret, str)):
        secrets = [secrets]

    values = set()
    for item in secrets:
        if item is None:
            continue
        value = item.reveal() if isinstance(item, Secret) else str(item)
        if len(value) >= MIN_REDACTABLE:
            values.add(value)

    # Longest first: when one credential contains another (a token and the
    # bearer header built from it), masking the short one first would leave
    # the rest of the long one sitting in the text.
    for value in sorted(values, key=len, reverse=True):
        result = result.replace(value, MASK)
    return result


# ---- the OS credential store, without the `keyring` dependency ------------

#: The CLI each platform already ships. Windows is absent on purpose: probing
#: for the PowerShell CredentialManager module costs a process launch per
#: lookup and answers "maybe", so Windows uses the file store, which works.
_PLATFORM_TOOLS = (("darwin", "security"), ("linux", "secret-tool"))


def keyring_available() -> bool:
    """Whether this machine has an OS credential store we can drive."""
    return _store_tool() is not None


def keyring_set(service: str, account: str, value: str) -> None:
    """Store a credential, in the OS store when there is one, else in a file."""
    tool = _store_tool()
    if tool == "security":
        # The value is an argv element, never a shell string: interpolating a
        # key into `sh -c` would let a quote in it run the rest as a command.
        _run_store(
            [tool, "add-generic-password", "-U", "-s", service, "-a", account, "-w", value],
            f"store {service}/{account} in the login keychain",
        )
    elif tool == "secret-tool":
        # secret-tool reads the value from stdin, which keeps it out of `ps`.
        _run_store(
            [tool, "store", "--label", f"{service}: {account}",
             "service", service, "account", account],
            f"store {service}/{account} in the secret service",
            stdin=value,
        )
    else:
        _file_store_write({**_file_store_read(), _entry_key(service, account): value})


def keyring_get(service: str, account: str) -> str | None:
    """Read a credential back, or ``None`` when it is not stored.

    Returns a bare ``str`` because it is the raw plumbing under
    :func:`resolve`, which is what wraps it in a :class:`Secret`.
    """
    tool = _store_tool()
    if tool == "security":
        argv = [tool, "find-generic-password", "-s", service, "-a", account, "-w"]
    elif tool == "secret-tool":
        argv = [tool, "lookup", "service", service, "account", account]
    else:
        return _file_store_read().get(_entry_key(service, account)) or None

    completed = _run_tool(argv)
    if completed is None or completed.returncode != 0:
        # "No such item" is the ordinary answer to a key that was never set.
        return None
    # rstrip("\n") rather than strip(): the tool adds a newline, but trailing
    # spaces inside a pasted credential are the user's problem to see, not
    # ours to silently repair.
    return completed.stdout.rstrip("\n") or None


def keyring_delete(service: str, account: str) -> bool:
    """Remove a credential. ``True`` only when something was actually there."""
    tool = _store_tool()
    if tool == "security":
        completed = _run_tool(
            [tool, "delete-generic-password", "-s", service, "-a", account]
        )
        return completed is not None and completed.returncode == 0
    if tool == "secret-tool":
        # `secret-tool clear` exits 0 whether or not it matched anything, so
        # ask first — a caller reporting "removed 1 key" must not invent the 1.
        if keyring_get(service, account) is None:
            return False
        completed = _run_tool([tool, "clear", "service", service, "account", account])
        return completed is not None and completed.returncode == 0

    entries = _file_store_read()
    if entries.pop(_entry_key(service, account), None) is None:
        return False
    _file_store_write(entries)
    return True


# ---- scheme handlers -----------------------------------------------------


def _resolve_env(name: str, base_dir: str | Path | None) -> Secret | None:
    return _wrap(os.environ.get(name))


def _resolve_keyring(body: str, base_dir: str | Path | None) -> Secret | None:
    service, separator, account = body.partition("/")
    if not separator or not service.strip() or not account.strip():
        raise SecretError(
            f"${{keyring:{body}}} is missing the account. "
            "Write it as ${keyring:service/account}, e.g. "
            "${keyring:agent-arena/openai}."
        )
    return _wrap(keyring_get(service.strip(), account.strip()))


def _resolve_file(body: str, base_dir: str | Path | None) -> Secret | None:
    path = Path(body).expanduser()
    if not path.is_absolute() and base_dir is not None:
        # Relative to the project that named it, not to whatever directory the
        # user happened to run `arena` from.
        path = Path(base_dir).expanduser() / path
    if not path.is_file():
        return None
    _require_private(path)
    try:
        return _wrap(path.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeDecodeError) as exc:
        raise SecretError(f"could not read the key file {path}: {exc}") from exc


def _resolve_cmd(body: str, base_dir: str | Path | None) -> Secret | None:
    # shlex.split, never shell=True. A credential helper is usually pasted from
    # a vendor's README, and `sh -c` would turn any `;` or backtick in it into
    # something the arena runs on the user's behalf.
    argv = shlex.split(body)
    if not argv:
        raise SecretError(
            "${cmd:...} needs a command, e.g. ${cmd:op read op://vault/item/field}"
        )
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SecretError(
            f"${{cmd:...}} cannot run {argv[0]!r}: it is not on PATH. "
            "Use the full path to the helper, or install it."
        ) from exc
    except OSError as exc:
        raise SecretError(f"${{cmd:...}} could not run {argv[0]!r}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SecretError(
            f"${{cmd:{body}}} did not finish within {COMMAND_TIMEOUT_S}s. "
            "A credential helper that waits for a prompt cannot be used here; "
            "unlock the vault first, or use ${env:...}."
        ) from exc

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip() or "no output on stderr"
        raise SecretError(
            f"${{cmd:{body}}} exited {completed.returncode}: {detail}"
        )
    return _wrap(completed.stdout.strip())


_HANDLERS = {
    "env": _resolve_env,
    "keyring": _resolve_keyring,
    "file": _resolve_file,
    "cmd": _resolve_cmd,
}


# ---- helpers -------------------------------------------------------------


def _wrap(value: str | None) -> Secret | None:
    """A value becomes a Secret; nothing becomes ``None``."""
    return Secret(value) if value else None


def _entry_key(service: str, account: str) -> str:
    return f"{service}/{account}"


def _store_tool() -> str | None:
    """The credential-store CLI for this platform, when it is installed."""
    for platform, tool in _PLATFORM_TOOLS:
        if sys.platform.startswith(platform):
            return tool if shutil.which(tool) else None
    return None


def _run_tool(argv: list[str], stdin: str | None = None):
    """Run a credential-store command, treating a missing tool as no answer."""
    try:
        return subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        # The tool was there when we probed and is not now, or it hung waiting
        # for a keychain prompt. Either way there is no credential to return.
        return None


def _run_store(argv: list[str], what: str, stdin: str | None = None) -> None:
    """Run a write against the OS store, or explain what failed.

    A failed *write* must raise: silently not saving a key looks identical to
    saving one, right up until the run that needed it.
    """
    completed = _run_tool(argv, stdin=stdin)
    if completed is None or completed.returncode != 0:
        detail = "" if completed is None else (completed.stderr or "").strip()
        raise SecretError(
            f"could not {what}: {detail or 'the credential tool did not run'}. "
            f"Check that {argv[0]!r} works from a terminal, or unset it to use "
            f"the file store at ~/{FALLBACK_STORE}."
        )


def _require_private(path: Path) -> None:
    """Refuse a credential file that other users on the machine can read.

    Reading it anyway would work, which is the problem: it teaches that a
    world-readable key file is fine, and the next one lives in a shared repo.
    """
    if os.name != "posix":
        # Windows reports 0o666 for every file; its ACLs are the real control
        # and these bits would only produce a refusal nobody could satisfy.
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise SecretError(
            f"{path} is readable by other users (mode {mode:04o}); "
            f"refusing to read a credential from it. Fix it with:\n"
            f"  chmod 600 {path}"
        )


def _fallback_path() -> Path:
    return Path.home() / FALLBACK_STORE


def _file_store_read() -> dict[str, str]:
    """The fallback store's contents, or ``{}`` when there is no file yet."""
    path = _fallback_path()
    if not path.is_file():
        return {}
    _require_private(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        # The message names the position, never the contents.
        raise SecretError(
            f"{path} is not readable JSON ({exc}). Delete it and store the "
            "credential again — the arena will recreate it."
        ) from exc
    if not isinstance(data, dict):
        raise SecretError(
            f"{path} must hold a JSON object of \"service/account\": \"value\" "
            "entries. Delete it and store the credential again."
        )
    return {str(key): str(value) for key, value in data.items()}


def _file_store_write(entries: dict[str, str]) -> None:
    path = _fallback_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # os.open with 0o600 so the file is never briefly world-readable, and an
    # explicit chmod after, because the umask masks the mode passed to open().
    handle = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(entries, stream, indent=2, sort_keys=True)
    if os.name == "posix":
        os.chmod(path, 0o600)


__all__ = [
    "MASK",
    "MIN_REDACTABLE",
    "SCHEMES",
    "Secret",
    "keyring_available",
    "keyring_delete",
    "keyring_get",
    "keyring_set",
    "provider_env",
    "redact",
    "resolve",
    "resolve_for_provider",
]
