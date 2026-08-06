"""The standard test-case schema: parsing, aliases, filtering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_arena.core.errors import TestCaseError
from agent_arena.core.testcase import (
    TestCase,
    filter_test_cases,
    load_test_cases,
    load_test_file,
)


def write(path: Path, data) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_required_fields_and_defaults() -> None:
    case = TestCase.parse({"input": "hello", "reference": "hi"}, index=0)

    assert case.input == "hello"
    assert case.reference == "hi"
    assert case.eval_type == "exact_match"
    assert case.weight == 1.0
    assert case.id == "case-000"


def test_missing_input_names_the_field() -> None:
    with pytest.raises(TestCaseError, match="missing required field 'input'"):
        TestCase.parse({"reference": "hi"}, index=3, source="t.json")


def test_field_aliases_are_accepted() -> None:
    case = TestCase.parse(
        {"prompt": "q", "expected": "a", "system": "be terse", "scorer": "contains"},
        index=0,
    )

    assert case.input == "q"
    assert case.reference == "a"
    assert case.context == "be terse"
    assert case.eval_type == "contains"


def test_message_list_input_is_preserved() -> None:
    case = TestCase.parse(
        {"input": [{"role": "user", "content": "one"}, {"role": "assistant", "content": "two"}],
         "reference": "x"},
        index=0,
    )

    assert isinstance(case.input, list)
    assert case.messages[1]["content"] == "two"


def test_malformed_message_list_is_rejected() -> None:
    with pytest.raises(TestCaseError, match="must be a mapping with a 'role'"):
        TestCase.parse({"input": [{"content": "no role"}], "reference": "x"}, index=0)


def test_string_input_becomes_a_user_message() -> None:
    case = TestCase.parse({"input": "hello", "reference": "x"}, index=0)

    assert case.messages == [{"role": "user", "content": "hello"}]


def test_unknown_fields_are_kept_as_metadata() -> None:
    case = TestCase.parse(
        {"input": "q", "reference": "a", "ticket_id": "T-9", "difficulty": 3}, index=0
    )

    assert case.metadata["ticket_id"] == "T-9"
    assert case.metadata["difficulty"] == 3


def test_defaults_block_applies_to_every_case(tmp_path: Path) -> None:
    path = write(
        tmp_path / "tests.json",
        {
            "defaults": {"eval_type": "contains", "tags": ["smoke"]},
            "tests": [
                {"id": "a", "input": "q", "reference": "a"},
                {"id": "b", "input": "q", "reference": "b", "eval_type": "regex"},
            ],
        },
    )
    cases = load_test_file(path)

    assert cases[0].eval_type == "contains"
    assert cases[1].eval_type == "regex"   # a case overrides the file default
    assert cases[0].tags == ["smoke"]


def test_jsonl_files_load(tmp_path: Path) -> None:
    path = tmp_path / "tests.jsonl"
    path.write_text(
        '{"id": "a", "input": "q", "reference": "a"}\n'
        "\n"
        '{"id": "b", "input": "q", "reference": "b"}\n',
        encoding="utf-8",
    )
    assert [c.id for c in load_test_file(path)] == ["a", "b"]


def test_disabled_cases_are_skipped(tmp_path: Path) -> None:
    path = write(
        tmp_path / "tests.json",
        [
            {"id": "a", "input": "q", "reference": "a"},
            {"id": "b", "input": "q", "reference": "b", "enabled": False},
            {"id": "c", "input": "q", "reference": "c", "skip": True},
        ],
    )
    assert [c.id for c in load_test_file(path)] == ["a"]


def test_duplicate_ids_across_files_are_rejected(tmp_path: Path) -> None:
    first = write(tmp_path / "tests.json", [{"id": "dup", "input": "q", "reference": "a"}])
    second = write(tmp_path / "more.json", [{"id": "dup", "input": "q", "reference": "b"}])

    with pytest.raises(TestCaseError, match="duplicate test id"):
        load_test_cases([first, second])


def _cases() -> list[TestCase]:
    return [
        TestCase(id="a", input="x", reference="x", tags=["easy", "billing"]),
        TestCase(id="b", input="x", reference="x", tags=["hard", "billing"]),
        TestCase(id="c", input="x", reference="x", tags=["easy"]),
    ]


def test_filter_by_any_tag() -> None:
    assert [c.id for c in filter_test_cases(_cases(), {"tags": ["billing"]})] == ["a", "b"]


def test_filter_by_all_tags() -> None:
    assert [c.id for c in filter_test_cases(_cases(), {"all_tags": ["easy", "billing"]})] == ["a"]


def test_filter_excludes_tags() -> None:
    assert [c.id for c in filter_test_cases(_cases(), {"exclude_tags": ["easy"]})] == ["b"]


def test_filter_by_ids_and_limit() -> None:
    assert [c.id for c in filter_test_cases(_cases(), {"ids": ["b", "c"]})] == ["b", "c"]
    assert [c.id for c in filter_test_cases(_cases(), {"limit": 2})] == ["a", "b"]


def test_filter_matching_nothing_is_an_error() -> None:
    with pytest.raises(TestCaseError, match="matched none"):
        filter_test_cases(_cases(), {"tags": ["nonexistent"]})


def test_unknown_id_in_filter_is_an_error() -> None:
    with pytest.raises(TestCaseError, match="unknown test id"):
        filter_test_cases(_cases(), {"ids": ["zzz"]})


def test_negative_weight_is_rejected() -> None:
    with pytest.raises(TestCaseError, match="must be >= 0"):
        TestCase.parse({"input": "q", "reference": "a", "weight": -1}, index=0)
