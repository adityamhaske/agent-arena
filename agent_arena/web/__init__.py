"""The browser UI: the arena without a terminal.

Everything here is a presentation layer over the same engine the CLI drives.
No evaluation logic lives in this package — if the UI and `arena evaluate`
ever disagreed about who won, the UI would be worthless.

Kept stdlib-only, like the engine: `python -m http.server`'s machinery plus a
few hundred lines of vanilla JS, so `pip install agent-arena` still pulls in
nothing but PyYAML.
"""

from __future__ import annotations

__all__ = ["serve", "build_app"]


def __getattr__(name: str):  # lazy: importing the CLI must not start a server
    if name in __all__:
        from .server import build_app, serve  # noqa: PLC0415

        return {"serve": serve, "build_app": build_app}[name]
    raise AttributeError(name)
