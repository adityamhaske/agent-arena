"""Project-specific escape hatches.

Some projects need to touch a model's output before it is graded — strip PII
before it reaches an LLM judge, normalise a date format, unwrap a envelope,
run a domain check. Rather than push that into every scorer, a project can
declare hooks::

    hooks:
      pre_request:  "hooks.py:add_retrieved_context"
      post_process: "hooks.py:strip_pii"

``post_process(output, test_case, context)`` returns either the replacement
output string, or a mapping to override the verdict outright::

    def strip_pii(output, test_case, context):
        return EMAIL_RE.sub("[email]", output)

    def check_schema(output, test_case, context):
        ok = validate(output)
        return {"output": output, "passed": ok, "score": 1.0 if ok else 0.0,
                "metrics": {"schema_errors": 0 if ok else 1}}

``pre_request(request, test_case, model_key)`` may mutate and return the
:class:`~agent_arena.connectors.base.GenerationRequest` before it is sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .errors import ArenaError, HookError
from .loaders import load_python_object

KNOWN_HOOKS = ("pre_request", "post_process", "on_result")


@dataclass
class PostProcessOutcome:
    """What a post-process hook decided."""

    output: str
    score: float | None = None
    passed: bool | None = None
    reason: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def overrides_verdict(self) -> bool:
        return self.score is not None or self.passed is not None


@dataclass
class HookSet:
    """The hooks a project declared, already imported."""

    pre_request: Callable[..., Any] | None = None
    post_process: Callable[..., Any] | None = None
    on_result: Callable[..., Any] | None = None

    @classmethod
    def load(cls, specs: dict[str, str], base_dir: Any = None) -> HookSet:
        unknown = set(specs) - set(KNOWN_HOOKS)
        if unknown:
            raise HookError(
                f"unknown hook(s): {', '.join(sorted(unknown))}. "
                f"Supported hooks: {', '.join(KNOWN_HOOKS)}"
            )
        resolved: dict[str, Callable[..., Any]] = {}
        for name, spec in specs.items():
            try:
                fn = load_python_object(spec, base_dir=base_dir)
            except ArenaError as exc:
                raise HookError(f"hooks.{name}: {exc}") from exc
            if not callable(fn):
                raise HookError(f"hooks.{name}: {spec} is not callable")
            resolved[name] = fn
        return cls(**resolved)

    # ---- invocation ---------------------------------------------------

    def apply_pre_request(self, request: Any, test_case: Any, model_key: str) -> Any:
        if self.pre_request is None:
            return request
        try:
            modified = self.pre_request(request, test_case, model_key)
        except Exception as exc:  # noqa: BLE001 — reported against the hook
            raise HookError(f"pre_request hook failed on {test_case.id}: {exc}") from exc
        return modified if modified is not None else request

    def apply_post_process(
        self, output: str, test_case: Any, context: Any
    ) -> PostProcessOutcome:
        if self.post_process is None:
            return PostProcessOutcome(output=output)
        try:
            result = self.post_process(output, test_case, context)
        except Exception as exc:  # noqa: BLE001 — reported against the hook
            raise HookError(f"post_process hook failed on {test_case.id}: {exc}") from exc

        if result is None:
            return PostProcessOutcome(output=output)
        if isinstance(result, str):
            return PostProcessOutcome(output=result)
        if isinstance(result, dict):
            return PostProcessOutcome(
                output=str(result.get("output", output)),
                score=_opt_float(result.get("score")),
                passed=result.get("passed"),
                reason=str(result.get("reason", "")),
                metrics={
                    k: float(v)
                    for k, v in (result.get("metrics") or {}).items()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)
                },
                detail=dict(result.get("detail") or {}),
            )
        raise HookError(
            f"post_process must return a string, a mapping, or None — got "
            f"{type(result).__name__}"
        )

    def apply_on_result(self, result: Any) -> None:
        if self.on_result is None:
            return
        try:
            self.on_result(result)
        except Exception as exc:  # noqa: BLE001 — reported against the hook
            raise HookError(f"on_result hook failed on {result.test_id}: {exc}") from exc


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise HookError(f"post_process returned a non-numeric score: {value!r}") from exc
