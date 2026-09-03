"""Credential management, on top of the primitives in :mod:`agent_arena.core.secrets`.

The resolution machinery itself lives in ``core`` so the connector registry can
reach it without importing ``service`` — see that module's docstring. What is
added here is the part that needs to know about providers: the fallback to a
vendor's conventional environment variable, read from the same table the
registry uses so the CLI and the UI cannot disagree about where a key lives.
"""

from __future__ import annotations

from pathlib import Path

from ..connectors import registry
from ..core.secrets import (
    COMMAND_TIMEOUT_S,
    SCHEMES,
    Secret,
    SecretError,
    keyring_available,
    keyring_delete,
    keyring_get,
    keyring_set,
    redact,
    resolve,
)
from .errors import ServiceError

__all__ = [
    "Secret", "SecretError", "ServiceError", "resolve", "resolve_for_provider",
    "provider_env", "redact", "keyring_available", "keyring_set", "keyring_get",
    "keyring_delete", "SCHEMES", "COMMAND_TIMEOUT_S",
]


def resolve_for_provider(
    kind: str, ref: str | None = None, *, base_dir: str | Path | None = None
) -> Secret | None:
    """The credential for a provider: the explicit reference, or its env var.

    The fallback is the vendor's conventional variable — ``ANTHROPIC_API_KEY``
    and friends — read from the same table the connector registry uses. If
    those two ever disagreed, a key that worked on the CLI would stop working
    in the UI, and the user would have no way to see why.
    """
    if ref:
        return resolve(ref, base_dir=base_dir)
    env_name = provider_env(kind)
    if env_name is None:
        # Local, mock and callable targets need no credential at all.
        return None
    return resolve("${env:%s}" % env_name)


def provider_env(kind: str) -> str | None:
    """The conventional API-key variable for a provider, or ``None``."""
    # Read through the module rather than copying the mapping: one table, so
    # the CLI and the UI cannot drift apart about where a key lives.
    return registry._API_KEY_ENVS.get(str(kind or "").strip().lower())
