"""Use cases, shared by every interface.

The CLI, the browser API and anyone importing :mod:`agent_arena` all reach the
same functions here. That is the point: before this layer existed, project
creation lived inside ``web/api.py`` and the CLI could not reach it, so the UI
could scaffold a project it could not delete and the CLI could delete nothing
at all. A capability lands here once and every interface gets it.

The dependency arrow points one way. This package may import from
:mod:`agent_arena.core`, :mod:`agent_arena.connectors` and
:mod:`agent_arena.scorers`; nothing here may import from
:mod:`agent_arena.web`, and nothing here knows about HTTP status codes,
argparse namespaces, or printing.
"""

from __future__ import annotations

from .errors import ConflictError, NotFoundError, ServiceError

__all__ = ["ServiceError", "NotFoundError", "ConflictError"]
