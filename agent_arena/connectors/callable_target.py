"""Evaluating a *system* rather than a single completion.

Almost nobody ships one prompt to one model any more. They ship a pipeline:
retrieve, plan, call tools, critique, synthesise. The arena's whole value —
your criteria, your constraints, a leaderboard that disqualifies what you
cannot ship — applies to those just as well, and until this connector existed
there was no supported way to point it at one.

A target is any Python callable::

    # pipelines/research.py
    def answer(prompt):
        docs = retrieve(prompt)
        return synthesise(prompt, docs)

declared beside the models it competes against::

    models:
      - key: pipeline_v1
        run: pipelines/research.py:answer
      - key: single_call_baseline      # the control, and a fair one
        model: claude-sonnet-5

An ``async def`` target is awaited for you — agent frameworks are async-first,
and making every adapter open with the same event-loop wrapper would be a tax
on the common case.

Everything downstream is unchanged: the same scorers grade it, the same
weights rank it, the same constraints can disqualify it.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from pathlib import Path
from typing import Any, Callable

from ..core.errors import ConnectorError
from ..core.loaders import load_python_object
from .base import Connector, GenerationRequest, GenerationResult, estimate_tokens

#: Keyword arguments offered to the target. A callable receives exactly the
#: subset it declares, so `def answer(prompt)` and
#: `def answer(prompt, *, tags, test_id)` both work and neither has to accept
#: arguments it does not care about.
CONTEXT_KEYS = ("messages", "system", "test_id", "trial", "tags", "params", "reference")

#: Keys a target may return to report what it actually spent. Anything it does
#: not report is left unmeasured rather than guessed — a fabricated cost would
#: be worse than no cost column.
USAGE_KEYS = ("input_tokens", "output_tokens", "cost_usd", "latency_ms")


class CallableConnector(Connector):
    """Runs a Python callable as if it were a model."""

    provider = "callable"

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        api_base: str | None = None,
        run: str | None = None,
        base_dir: str | Path | None = None,
        **params: Any,
    ) -> None:
        super().__init__(model, api_key=api_key, api_base=api_base, **params)
        spec = run or model
        if not spec or ":" not in str(spec):
            raise ConnectorError(
                f"target {model!r} needs `run: path/to/file.py:function` "
                "(or `package.module:function`)"
            )
        self.spec = str(spec)
        self.base_dir = Path(base_dir) if base_dir else None
        self._fn: Callable[..., Any] | None = None
        self._accepts: set[str] | None = None
        self._takes_kwargs = False

    # ---- loading -------------------------------------------------------

    def _load(self) -> Callable[..., Any]:
        """Import on first use, then cache — a target is called once per case."""
        if self._fn is None:
            fn = load_python_object(self.spec, base_dir=self.base_dir)
            if not callable(fn):
                raise ConnectorError(f"{self.spec} is not callable")
            self._fn = fn
            self._accepts, self._takes_kwargs = _signature_of(fn)
        return self._fn

    def healthcheck(self) -> str | None:
        """Import the target before the run, so a typo costs nothing."""
        try:
            self._load()
        except Exception as exc:  # noqa: BLE001 — reported, not raised
            return f"{type(exc).__name__}: {exc}"
        return None

    # ---- calling -------------------------------------------------------

    def generate(self, request: GenerationRequest) -> GenerationResult:
        fn = self._load()

        context = {
            "messages": request.messages,
            "system": request.system,
            "test_id": request.metadata.get("test_id"),
            "trial": request.metadata.get("trial"),
            "tags": request.metadata.get("tags") or [],
            "params": {**self.params, **request.params},
            "reference": request.metadata.get("reference"),
        }
        kwargs = (
            dict(context)
            if self._takes_kwargs
            else {k: v for k, v in context.items() if k in (self._accepts or set())}
        )

        started = time.perf_counter()
        raw = fn(request.prompt, **kwargs)
        if inspect.isawaitable(raw):
            # Agent frameworks are async-first — LangGraph, LlamaIndex and most
            # tool loops hand you a coroutine. Driving it here means a target
            # can be written the way its own codebase already is, instead of
            # every adapter opening with the same `asyncio.run` wrapper.
            raw = _resolve(raw)
        measured = (time.perf_counter() - started) * 1000.0

        text, usage, metrics = _unpack(raw, self.spec)
        return GenerationResult(
            text=text,
            model=self.model,
            provider=self.provider,
            input_tokens=int(usage.get("input_tokens") or 0)
            or estimate_tokens(request.prompt),
            output_tokens=int(usage.get("output_tokens") or 0) or estimate_tokens(text),
            # A pipeline knows its own end-to-end cost across every internal
            # call; we cannot, so we only report what it tells us.
            latency_ms=float(usage["latency_ms"]) if usage.get("latency_ms") else measured,
            finish_reason="stop",
            cost_usd=float(usage["cost_usd"]) if usage.get("cost_usd") is not None else None,
            metrics=metrics,
            raw={"target": self.spec},
        )


def _resolve(awaitable: Any) -> Any:
    """Drive a coroutine to completion from a synchronous caller.

    The runner calls connectors on worker threads, which have no event loop, so
    this is `asyncio.run` in every real sweep. The other branch is for anyone
    embedding the runner inside their own async program: a loop is already
    running on this thread, and `asyncio.run` would refuse, so the coroutine
    gets its own loop on a thread of its own.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, awaitable).result()


def _signature_of(fn: Callable[..., Any]) -> tuple[set[str], bool]:
    """Which context kwargs this target accepts, and whether it takes **kwargs."""
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):  # builtins and C callables
        return set(), False

    accepts: set[str] = set()
    takes_kwargs = False
    for index, parameter in enumerate(signature.parameters.values()):
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            takes_kwargs = True
        elif parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        elif index == 0 and parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            continue  # the prompt, passed positionally
        elif parameter.name in CONTEXT_KEYS:
            accepts.add(parameter.name)
    return accepts, takes_kwargs


def _unpack(raw: Any, spec: str) -> tuple[str, dict[str, Any], dict[str, float]]:
    """Accept the two shapes a pipeline naturally returns."""
    if raw is None:
        return "", {}, {}
    if isinstance(raw, str):
        return raw, {}, {}
    if isinstance(raw, dict):
        text = raw.get("output", raw.get("text", raw.get("answer")))
        if text is None:
            raise ConnectorError(
                f"{spec} returned a dict with no 'output' (or 'text'/'answer') key. "
                "Return a string, or a mapping like "
                "{'output': ..., 'input_tokens': ..., 'cost_usd': ...}."
            )
        usage = {key: raw[key] for key in USAGE_KEYS if raw.get(key) is not None}
        metrics = {
            str(name): float(value)
            for name, value in (raw.get("metrics") or {}).items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        return str(text), usage, metrics
    # Anything else (a dataclass, a custom result object) — take its text if it
    # has one rather than stringifying something unhelpful.
    for attribute in ("output", "text", "answer"):
        if hasattr(raw, attribute):
            return str(getattr(raw, attribute)), {}, {}
    raise ConnectorError(
        f"{spec} returned {type(raw).__name__}; expected a string or a mapping "
        "with an 'output' key."
    )
