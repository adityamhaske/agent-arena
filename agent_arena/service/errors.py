"""Errors the service layer raises.

These sit under :class:`~agent_arena.core.errors.ArenaError` so a caller that
already handles arena failures keeps working, while an interface that wants to
map them onto something specific — an HTTP status, an exit code — can tell the
three cases apart without parsing a message.
"""

from __future__ import annotations

from ..core.errors import ArenaError


class ServiceError(ArenaError):
    """A caller asked for something that is not valid."""


class NotFoundError(ServiceError):
    """The named project, run, or provider does not exist."""


class ConflictError(ServiceError):
    """The request collides with existing state — a duplicate name, or a busy run."""
