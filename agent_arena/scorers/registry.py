"""Scorer lookup: ``eval_type`` string in, ready-to-use scorer out.

Built-in scorers are registered on construction; project-local ones are
discovered by importing every ``.py`` file under the paths listed in
``scorers.paths``. Three registration styles are recognised, so a project can
use whichever reads best:

* a :class:`~agent_arena.scorers.base.Scorer` subclass with a ``name``
* a module-level ``SCORERS = {"name": ScorerClass}`` mapping
* a function decorated with ``@scorer("name")``
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Callable, Iterable

from ..core.errors import ScorerError
from ..core.loaders import load_module_from_path
from .base import FunctionScorer, Scorer
from .builtin import BUILTIN_SCORERS


class ScorerRegistry:
    """Maps ``eval_type`` names to scorer factories."""

    def __init__(self, options: dict[str, dict[str, Any]] | None = None) -> None:
        self._factories: dict[str, Callable[..., Scorer]] = dict(BUILTIN_SCORERS)
        self._options = options or {}
        self._cache: dict[str, Scorer] = {}
        self._sources: dict[str, str] = {name: "builtin" for name in BUILTIN_SCORERS}

    # ---- registration -------------------------------------------------

    def register(
        self, name: str, factory: Callable[..., Scorer], source: str = "custom"
    ) -> None:
        if not name:
            raise ScorerError("cannot register a scorer with an empty name")
        self._factories[name] = factory
        self._sources[name] = source
        self._cache.pop(name, None)

    def load_paths(self, paths: Iterable[str | Path], base_dir: str | Path | None = None) -> int:
        """Import every Python file under ``paths`` and register what it defines."""
        loaded = 0
        for entry in paths:
            path = Path(entry)
            if base_dir is not None and not path.is_absolute():
                path = Path(base_dir) / path
            files = (
                sorted(p for p in path.rglob("*.py") if not p.name.startswith("_"))
                if path.is_dir()
                else [path]
            )
            for file in files:
                loaded += self.load_module(file)
        return loaded

    def load_module(self, path: str | Path) -> int:
        """Register every scorer defined in one Python file."""
        path = Path(path)
        module = load_module_from_path(path)
        registered = 0

        explicit = getattr(module, "SCORERS", None)
        if isinstance(explicit, dict):
            for name, factory in explicit.items():
                self.register(str(name), factory, source=str(path))
                registered += 1

        for _, obj in inspect.getmembers(module):
            if (
                inspect.isclass(obj)
                and issubclass(obj, Scorer)
                and obj not in (Scorer, FunctionScorer)
                and getattr(obj, "name", "")
                and not inspect.isabstract(obj)
            ):
                self.register(obj.name, obj, source=str(path))
                registered += 1
            elif inspect.isfunction(obj) and hasattr(obj, "_arena_scorer_name"):
                name = obj._arena_scorer_name
                requires_ref = getattr(obj, "_arena_requires_reference", True)
                self.register(
                    name,
                    _function_factory(obj, name, requires_ref),
                    source=str(path),
                )
                registered += 1

        if registered == 0:
            raise ScorerError(
                f"{path} defines no scorers. Export a Scorer subclass with a `name`, "
                "a SCORERS dict, or a function decorated with @scorer('name')."
            )
        return registered

    # ---- lookup -------------------------------------------------------

    def get(self, name: str) -> Scorer:
        if name in self._cache:
            return self._cache[name]

        factory = self._factories.get(name)
        if factory is None:
            available = ", ".join(sorted(self._factories))
            raise ScorerError(
                f"unknown eval_type {name!r}. Available: {available}.\n"
                "Add a custom scorer under the project's scorers/ folder and list "
                "the folder in `scorers.paths` to extend this."
            )

        options = dict(self._options.get(name, {}))
        try:
            instance = factory(**options) if options else factory()
        except TypeError as exc:
            raise ScorerError(
                f"could not construct scorer {name!r} with options {options!r}: {exc}"
            ) from exc

        if not isinstance(instance, Scorer):
            if callable(instance):
                instance = FunctionScorer(instance, name)
            else:
                raise ScorerError(
                    f"scorer {name!r} factory returned {type(instance).__name__}, "
                    "expected a Scorer instance"
                )
        if not instance.name:
            instance.name = name

        self._cache[name] = instance
        return instance

    def __contains__(self, name: object) -> bool:
        return name in self._factories

    @property
    def names(self) -> list[str]:
        return sorted(self._factories)

    def describe(self) -> list[dict[str, str]]:
        """Rows for ``arena scorers`` — name, source, and one-line description."""
        rows = []
        for name in self.names:
            factory = self._factories[name]
            doc = getattr(factory, "description", "") or (
                inspect.getdoc(factory) or ""
            ).strip().split("\n")[0]
            rows.append(
                {"name": name, "source": self._sources.get(name, "custom"), "description": doc}
            )
        return rows


def _function_factory(fn: Callable[..., Any], name: str, requires_reference: bool):
    def factory(**options: Any) -> Scorer:
        instance = FunctionScorer(fn, name, **options)
        instance.requires_reference = requires_reference
        return instance

    return factory


def build_registry(config: Any) -> ScorerRegistry:
    """Construct a registry for a loaded :class:`ProjectConfig`."""
    registry = ScorerRegistry(options=getattr(config, "scorer_options", {}))
    paths = getattr(config, "scorer_paths", None)
    if paths:
        registry.load_paths(paths, base_dir=getattr(config, "root", None))
    else:
        # Convention over configuration: a scorers/ folder is picked up for free.
        default_dir = Path(getattr(config, "root", ".")) / "scorers"
        if default_dir.is_dir() and any(default_dir.glob("*.py")):
            registry.load_paths([default_dir])
    return registry
