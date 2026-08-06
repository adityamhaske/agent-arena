"""The standard test-case schema.

Every project describes its work in the same shape, whatever the project
actually does:

.. code-block:: yaml

    - id: refund_intent
      input: "My order never arrived, I want my money back."
      reference: refund
      eval_type: exact_match      # optional — falls back to scorers.default
      context: "Classify the ticket. Reply with one word."   # system prompt
      tags: [billing, easy]
      max_tokens: 16
      temperature: 0
      weight: 2                   # counts double toward accuracy
      params: {case_sensitive: false}   # passed through to the scorer

Files may be JSON, JSONL or YAML, and may be either a bare list of cases or a
mapping with a ``tests:`` key plus a ``defaults:`` block applied to every case
in that file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from .errors import ArenaError, TestCaseError
from .loaders import load_structured

_INPUT_KEYS = ("input", "prompt", "question", "messages", "text")
_REFERENCE_KEYS = ("reference", "expected", "answer", "target", "gold")
_CONTEXT_KEYS = ("context", "system", "system_prompt", "instructions")

_RESERVED = {
    *_INPUT_KEYS,
    *_REFERENCE_KEYS,
    *_CONTEXT_KEYS,
    "id",
    "name",
    "eval_type",
    "evaluator",
    "scorer",
    "type",
    "tags",
    "weight",
    "max_tokens",
    "temperature",
    "params",
    "options",
    "metadata",
    "enabled",
    "skip",
}


@dataclass
class TestCase:
    """One unit of work sent to every model under test."""

    id: str
    input: str | list[dict[str, Any]]
    reference: Any = None
    eval_type: str = "exact_match"
    context: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    tags: list[str] = field(default_factory=list)
    weight: float = 1.0
    params: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str | None = None

    @property
    def has_reference(self) -> bool:
        return self.reference is not None

    @property
    def messages(self) -> list[dict[str, Any]]:
        """The input as a provider-neutral message list."""
        if isinstance(self.input, list):
            return self.input
        return [{"role": "user", "content": str(self.input)}]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "input": self.input,
            "reference": self.reference,
            "eval_type": self.eval_type,
            "context": self.context,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "tags": list(self.tags),
            "weight": self.weight,
            "params": dict(self.params),
            "metadata": dict(self.metadata),
            "source": self.source,
        }

    @classmethod
    def parse(
        cls,
        raw: Any,
        *,
        index: int,
        source: str | None = None,
        defaults: dict[str, Any] | None = None,
        default_eval_type: str = "exact_match",
    ) -> TestCase:
        where = f"{source or '<inline>'}[{index}]"
        if not isinstance(raw, dict):
            raise TestCaseError(f"{where}: each test case must be a mapping, got {type(raw).__name__}")

        merged: dict[str, Any] = dict(defaults or {})
        merged.update(raw)

        value = _first_present(merged, _INPUT_KEYS)
        if value is None:
            raise TestCaseError(
                f"{where}: missing required field 'input' "
                f"(accepted aliases: {', '.join(_INPUT_KEYS)})"
            )
        if isinstance(value, list):
            for i, message in enumerate(value):
                if not isinstance(message, dict) or "role" not in message:
                    raise TestCaseError(
                        f"{where}: input[{i}] must be a mapping with a 'role' key "
                        "when input is a message list"
                    )
            test_input: str | list[dict[str, Any]] = value
        else:
            test_input = str(value)

        eval_type = (
            merged.get("eval_type")
            or merged.get("evaluator")
            or merged.get("scorer")
            or merged.get("type")
            or default_eval_type
        )

        tags = merged.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        elif not isinstance(tags, (list, tuple)):
            raise TestCaseError(f"{where}: 'tags' must be a string or list of strings")

        weight = merged.get("weight", 1.0)
        try:
            weight = float(weight)
        except (TypeError, ValueError) as exc:
            raise TestCaseError(f"{where}: 'weight' must be a number, got {weight!r}") from exc
        if weight < 0:
            raise TestCaseError(f"{where}: 'weight' must be >= 0")

        params = merged.get("params") or merged.get("options") or {}
        if not isinstance(params, dict):
            raise TestCaseError(f"{where}: 'params' must be a mapping")

        metadata = dict(merged.get("metadata") or {})
        # Anything unrecognised is kept as metadata rather than silently dropped —
        # projects routinely carry their own bookkeeping fields on test cases.
        for key, value in merged.items():
            if key not in _RESERVED and key not in metadata:
                metadata[key] = value

        case_id = merged.get("id") or merged.get("name")
        if not case_id:
            stem = Path(source).stem if source else "case"
            case_id = f"{stem}-{index:03d}"

        return cls(
            id=str(case_id),
            input=test_input,
            reference=_first_present(merged, _REFERENCE_KEYS),
            eval_type=str(eval_type),
            context=_coerce_optional_str(_first_present(merged, _CONTEXT_KEYS)),
            max_tokens=_coerce_optional_int(merged.get("max_tokens"), f"{where}.max_tokens"),
            temperature=_coerce_optional_float(merged.get("temperature"), f"{where}.temperature"),
            tags=[str(t) for t in tags],
            weight=weight,
            params=dict(params),
            metadata=metadata,
            source=source,
        )


def _first_present(data: dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _coerce_optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _coerce_optional_int(value: Any, where: str) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise TestCaseError(f"{where} must be an integer, got {value!r}") from exc


def _coerce_optional_float(value: Any, where: str) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise TestCaseError(f"{where} must be a number, got {value!r}") from exc


def load_test_file(path: str | Path, default_eval_type: str = "exact_match") -> list[TestCase]:
    """Read one test file into ``TestCase`` objects."""
    path = Path(path)
    try:
        data = load_structured(path)
    except ArenaError as exc:
        raise TestCaseError(str(exc)) from exc

    defaults: dict[str, Any] = {}
    if isinstance(data, dict):
        defaults = data.get("defaults") or {}
        if not isinstance(defaults, dict):
            raise TestCaseError(f"{path}: 'defaults' must be a mapping")
        records = data.get("tests", data.get("cases", data.get("test_cases")))
        if records is None:
            raise TestCaseError(
                f"{path}: mapping-style test files need a 'tests:' key holding the list of cases"
            )
    else:
        records = data

    if not isinstance(records, list):
        raise TestCaseError(f"{path}: expected a list of test cases, got {type(records).__name__}")

    cases: list[TestCase] = []
    for index, record in enumerate(records):
        if isinstance(record, dict) and (
            record.get("enabled") is False or record.get("skip") is True
        ):
            continue
        cases.append(
            TestCase.parse(
                record,
                index=index,
                source=str(path),
                defaults=defaults,
                default_eval_type=default_eval_type,
            )
        )
    return cases


def load_test_cases(
    paths: Iterable[str | Path],
    default_eval_type: str = "exact_match",
    test_filter: dict[str, Any] | None = None,
) -> list[TestCase]:
    """Load and filter every test case across the given files."""
    cases: list[TestCase] = []
    for path in paths:
        cases.extend(load_test_file(path, default_eval_type=default_eval_type))

    seen: dict[str, str] = {}
    for case in cases:
        if case.id in seen:
            raise TestCaseError(
                f"duplicate test id {case.id!r} in {case.source} "
                f"(already defined in {seen[case.id]}); ids must be unique across the project"
            )
        seen[case.id] = case.source or "<inline>"

    return filter_test_cases(cases, test_filter or {})


def filter_test_cases(cases: list[TestCase], test_filter: dict[str, Any]) -> list[TestCase]:
    """Apply ``tags`` / ``all_tags`` / ``exclude_tags`` / ``ids`` / ``limit`` filters."""
    if not test_filter:
        return cases

    selected = cases

    ids = test_filter.get("ids")
    if ids:
        wanted = {str(i) for i in _listify(ids)}
        selected = [c for c in selected if c.id in wanted]
        missing = wanted - {c.id for c in selected}
        if missing:
            raise TestCaseError(f"unknown test id(s): {', '.join(sorted(missing))}")

    any_tags = test_filter.get("tags") or test_filter.get("tags_any")
    if any_tags:
        wanted = {str(t) for t in _listify(any_tags)}
        selected = [c for c in selected if wanted & set(c.tags)]

    all_tags = test_filter.get("all_tags") or test_filter.get("tags_all")
    if all_tags:
        wanted = {str(t) for t in _listify(all_tags)}
        selected = [c for c in selected if wanted <= set(c.tags)]

    exclude = test_filter.get("exclude_tags")
    if exclude:
        unwanted = {str(t) for t in _listify(exclude)}
        selected = [c for c in selected if not (unwanted & set(c.tags))]

    limit = test_filter.get("limit")
    if limit:
        selected = selected[: int(limit)]

    if not selected:
        raise TestCaseError(
            f"test filter {test_filter!r} matched none of the {len(cases)} loaded test cases"
        )
    return selected


def _listify(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]
