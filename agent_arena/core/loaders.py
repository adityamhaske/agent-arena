"""Format-agnostic loading of structured data files and Python plugins.

Two things every part of the arena needs and neither should reimplement:
reading a JSON/JSONL/YAML file into Python, and importing a Python object from
a path outside the package (project-local scorers and hooks).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from .errors import ArenaError

STRUCTURED_SUFFIXES = (".yaml", ".yml", ".json", ".jsonl", ".ndjson")


def yaml_available() -> bool:
    return importlib.util.find_spec("yaml") is not None


def load_structured(path: str | Path) -> Any:
    """Load a JSON, JSONL or YAML file into plain Python objects.

    YAML needs PyYAML; if it is missing we say so instead of failing with an
    ``ImportError`` from three frames down.
    """
    path = Path(path)
    if not path.is_file():
        raise ArenaError(f"No such file: {path}")

    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    if suffix in (".jsonl", ".ndjson"):
        records = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ArenaError(f"{path}:{lineno}: invalid JSON — {exc}") from exc
        return records

    if suffix == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ArenaError(f"{path}: invalid JSON — {exc}") from exc

    if suffix in (".yaml", ".yml"):
        if not yaml_available():
            raise ArenaError(
                f"{path} is YAML but PyYAML is not installed. "
                "Install it (`pip install pyyaml`) or use the .json/.jsonl equivalent."
            )
        import yaml  # noqa: PLC0415 — optional dependency, imported on demand

        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ArenaError(f"{path}: invalid YAML — {exc}") from exc

    raise ArenaError(
        f"{path}: unsupported file type {suffix!r}. "
        f"Expected one of {', '.join(STRUCTURED_SUFFIXES)}."
    )


def load_python_object(spec: str, base_dir: str | Path | None = None) -> Any:
    """Import an object from ``"module_or_path.py:attribute"`` or ``"pkg.mod:attr"``.

    Project-local plugins live outside any installed package, so a file path is
    loaded through ``importlib`` machinery under a unique module name — two
    projects can both ship a ``scorers.py`` without colliding in
    ``sys.modules``.
    """
    if ":" not in spec:
        raise ArenaError(
            f"Cannot load {spec!r}: expected 'path/to/file.py:function' "
            "or 'package.module:function'."
        )
    target, _, attr = spec.partition(":")

    candidate = Path(target)
    if base_dir is not None and not candidate.is_absolute():
        candidate = Path(base_dir) / candidate

    if candidate.suffix == ".py" or candidate.is_file():
        module = load_module_from_path(candidate)
    else:
        import importlib  # noqa: PLC0415

        try:
            module = importlib.import_module(target)
        except ImportError as exc:
            raise ArenaError(f"Cannot import module {target!r}: {exc}") from exc

    if not hasattr(module, attr):
        raise ArenaError(f"{target} has no attribute {attr!r}")
    return getattr(module, attr)


def load_module_from_path(path: str | Path):
    """Import a .py file as an anonymous module, without polluting sys.modules."""
    path = Path(path)
    if not path.is_file():
        raise ArenaError(f"No such Python file: {path}")

    module_name = f"_arena_plugin_{path.stem}_{uuid.uuid4().hex[:8]}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ArenaError(f"Cannot load Python file: {path}")

    module = importlib.util.module_from_spec(spec)
    # Registered before exec so dataclasses/pickle inside the plugin resolve,
    # then removed so repeated loads never see a stale module.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 — surfaced with the file that failed
        sys.modules.pop(module_name, None)
        raise ArenaError(f"Error importing {path}: {type(exc).__name__}: {exc}") from exc
    finally:
        sys.modules.pop(module_name, None)
    return module
