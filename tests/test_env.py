"""What `.env` support promises, and what it must never do.

Three things make this module worth pinning down. The parser follows shell
quoting conventions, and every one of them is a way to corrupt an API key
silently — an escape expanded inside single quotes, a value truncated at a
`#`, a stray line taken as fatal. Precedence is the second: an exported key
must beat a stale file, or a user rotates a credential and the arena keeps
using the old one. The third is that a missing file is ordinary, because most
projects will never have a `.env` at all.

These tests restore `os.environ` themselves: `load_env` writes to the real
process environment, so a leak here would follow the rest of the suite.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_arena.core.env import find_env_files, load_env, parse_env


@pytest.fixture()
def clean_environ():
    """Snapshot and restore os.environ around a test that calls load_env."""
    saved = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point Path.home() at a temp directory, so the developer's own
    ~/.config/agent-arena/.env can never influence a test."""
    fake_home = tmp_path / "home"
    (fake_home / ".config" / "agent-arena").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    return fake_home


def user_env(home: Path) -> Path:
    return home / ".config" / "agent-arena" / ".env"


# ---- parsing ----------------------------------------------------------


def test_plain_assignment_is_read() -> None:
    assert parse_env("KEY=value") == {"KEY": "value"}


def test_export_prefix_is_accepted() -> None:
    # People paste lines straight out of their shell profile.
    assert parse_env("export ANTHROPIC_API_KEY=sk-1") == {"ANTHROPIC_API_KEY": "sk-1"}


def test_blank_lines_and_own_line_comments_are_ignored() -> None:
    text = "\n# a note\n\n   # an indented note\nKEY=value\n"

    assert parse_env(text) == {"KEY": "value"}


def test_trailing_comment_is_stripped_from_an_unquoted_value() -> None:
    assert parse_env("KEY=value   # why this key exists") == {"KEY": "value"}


def test_hash_inside_a_value_is_not_a_comment() -> None:
    # Truncating `sk-ab#cd` would send the provider a subtly wrong key.
    assert parse_env("KEY=sk-ab#cd") == {"KEY": "sk-ab#cd"}


def test_unquoted_values_lose_surrounding_whitespace() -> None:
    assert parse_env("KEY=   value   ") == {"KEY": "value"}


def test_quoted_values_keep_their_whitespace() -> None:
    assert parse_env('KEY="  padded  "') == {"KEY": "  padded  "}
    assert parse_env("KEY='  padded  '") == {"KEY": "  padded  "}


def test_comment_after_a_quoted_value_is_stripped() -> None:
    assert parse_env('KEY="value"  # note') == {"KEY": "value"}


def test_hash_inside_quotes_stays_in_the_value() -> None:
    assert parse_env('KEY="a # b"') == {"KEY": "a # b"}


def test_double_quotes_expand_escape_sequences() -> None:
    parsed = parse_env(r'KEY="a\nb\tc \"q\" \\"')

    assert parsed == {"KEY": 'a\nb\tc "q" \\'}


def test_single_quotes_keep_escape_sequences_literal() -> None:
    # The asymmetry is the shell's, and getting it backwards turns a
    # two-character sequence in a key into a newline nobody can see.
    parsed = parse_env(r"KEY='a\nb'")

    assert parsed == {"KEY": r"a\nb"}
    assert "\n" not in parsed["KEY"]


def test_unknown_escape_is_left_alone() -> None:
    assert parse_env(r'KEY="C:\Users"') == {"KEY": r"C:\Users"}


def test_value_may_contain_equals_signs() -> None:
    assert parse_env("KEY=a=b=c") == {"KEY": "a=b=c"}


def test_empty_value_is_allowed() -> None:
    assert parse_env("KEY=") == {"KEY": ""}


def test_later_line_wins_for_a_repeated_key() -> None:
    assert parse_env("KEY=first\nKEY=second") == {"KEY": "second"}


@pytest.mark.parametrize(
    "line",
    [
        "this is not an assignment",
        "=novalue",
        "2FA=leading digit",
        'KEY="unterminated',
        "KEY='unterminated",
        'KEY="value" trailing junk',
    ],
)
def test_malformed_lines_are_skipped_not_fatal(line: str) -> None:
    text = f"GOOD=1\n{line}\nALSO_GOOD=2\n"

    # No raise: one bad line must never cost someone their evaluation.
    assert parse_env(text) == {"GOOD": "1", "ALSO_GOOD": "2"}


# ---- locating files ---------------------------------------------------


def test_no_env_files_anywhere_is_not_an_error(tmp_path: Path, home: Path) -> None:
    assert find_env_files(tmp_path) == []


def test_home_file_comes_before_the_project_file(tmp_path: Path, home: Path) -> None:
    user_env(home).write_text("A=1\n", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text("B=2\n", encoding="utf-8")

    # Nearest last, so a caller applying them in order lets the project win.
    assert find_env_files(project) == [user_env(home), project / ".env"]


def test_a_config_file_can_stand_in_for_its_folder(tmp_path: Path, home: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text("B=2\n", encoding="utf-8")
    config = project / "config.yaml"
    config.write_text("project: x\n", encoding="utf-8")

    assert find_env_files(config) == [project / ".env"]


# ---- loading into os.environ ------------------------------------------


def test_load_env_sets_and_reports_what_it_set(
    tmp_path: Path, home: Path, clean_environ
) -> None:
    os.environ.pop("ARENA_TEST_KEY", None)
    (tmp_path / ".env").write_text("ARENA_TEST_KEY=from-file\n", encoding="utf-8")

    applied = load_env(tmp_path)

    assert applied == {"ARENA_TEST_KEY": "from-file"}
    assert os.environ["ARENA_TEST_KEY"] == "from-file"


def test_real_environment_wins_over_the_file(
    tmp_path: Path, home: Path, clean_environ
) -> None:
    os.environ["ARENA_TEST_KEY"] = "from-shell"
    (tmp_path / ".env").write_text("ARENA_TEST_KEY=from-file\n", encoding="utf-8")

    applied = load_env(tmp_path)

    # An explicit export is the user's most deliberate statement of intent;
    # the file may be months stale.
    assert os.environ["ARENA_TEST_KEY"] == "from-shell"
    assert applied == {}


def test_override_replaces_the_real_environment(
    tmp_path: Path, home: Path, clean_environ
) -> None:
    os.environ["ARENA_TEST_KEY"] = "from-shell"
    (tmp_path / ".env").write_text("ARENA_TEST_KEY=from-file\n", encoding="utf-8")

    applied = load_env(tmp_path, override=True)

    assert os.environ["ARENA_TEST_KEY"] == "from-file"
    assert applied == {"ARENA_TEST_KEY": "from-file"}


def test_project_file_beats_the_home_file(
    tmp_path: Path, home: Path, clean_environ
) -> None:
    os.environ.pop("ARENA_TEST_KEY", None)
    os.environ.pop("ARENA_TEST_SHARED", None)
    user_env(home).write_text(
        "ARENA_TEST_KEY=from-home\nARENA_TEST_SHARED=shared\n", encoding="utf-8"
    )
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text("ARENA_TEST_KEY=from-project\n", encoding="utf-8")

    applied = load_env(project)

    assert applied["ARENA_TEST_KEY"] == "from-project"
    assert applied["ARENA_TEST_SHARED"] == "shared"
    assert os.environ["ARENA_TEST_KEY"] == "from-project"


def test_missing_files_leave_the_environment_alone(
    tmp_path: Path, home: Path, clean_environ
) -> None:
    before = dict(os.environ)

    assert load_env(tmp_path / "does-not-exist") == {}
    assert dict(os.environ) == before


def test_a_malformed_file_still_yields_its_good_lines(
    tmp_path: Path, home: Path, clean_environ
) -> None:
    os.environ.pop("ARENA_TEST_KEY", None)
    (tmp_path / ".env").write_text(
        "garbage line\nARENA_TEST_KEY=works\n", encoding="utf-8"
    )

    assert load_env(tmp_path) == {"ARENA_TEST_KEY": "works"}
