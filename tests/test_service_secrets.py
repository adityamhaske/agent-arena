"""Tests for credential handling.

Two things here are worth protecting and nothing else is:

* **that a credential cannot be stringified**, because the failure is silent.
  A key that leaks into a log line, an error message or an exported report is
  not something the user finds out about — it is something an attacker does.
  Every test that asserts on ``repr``/``str``/f-strings exists for that.
* **that ``${cmd:...}`` never reaches a shell**, because these references are
  pasted out of vendor READMEs, and one that happens to contain ``;`` would
  otherwise become something the arena runs on the user's behalf.

The resolution rules themselves (unset means ``None``, a literal stays a
literal) are tested because callers branch on them: a local model legitimately
has no credential, and treating that as an error would break offline runs.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from agent_arena.connectors import registry
from agent_arena.core.errors import SecretError
from agent_arena.service.secrets import (
    Secret,
    provider_env,
    redact,
    resolve,
    resolve_for_provider,
)

VALUE = "sk-ant-api03-not-a-real-key-9876543210"


# ---------------------------------------------------------------- redaction


def test_a_secret_never_reveals_itself_through_any_stringification():
    secret = Secret(VALUE)
    rendered = f"{secret} {secret!r} {secret!s} {json.dumps({'k': secret}, default=str)}"
    assert VALUE not in rendered
    assert rendered.count("***") == 4


def test_reveal_is_the_only_way_out():
    assert Secret(VALUE).reveal() == VALUE


def test_a_secret_is_not_a_str_subclass():
    # Inheriting from str would give it str.__str__ back and defeat the point.
    assert not isinstance(Secret(VALUE), str)


def test_an_empty_secret_is_falsey_so_callers_can_test_it_plainly():
    assert not Secret("")
    assert Secret(VALUE)


def test_secrets_compare_by_value():
    assert Secret(VALUE) == Secret(VALUE)
    assert Secret(VALUE) != Secret("other")


def test_redact_replaces_a_key_that_leaked_into_an_error_message():
    message = f"POST /v1/chat failed: Authorization: Bearer {VALUE}"
    assert VALUE not in redact(message, [Secret(VALUE)])


def test_redact_leaves_short_values_alone():
    # Blanking a two-character "secret" would mangle unrelated prose without
    # protecting anything a real key looks like.
    assert redact("a cost of 42 dollars", [Secret("42")]) == "a cost of 42 dollars"


# --------------------------------------------------------------- references


def test_env_reference_resolves(monkeypatch):
    monkeypatch.setenv("ARENA_TEST_SECRET", VALUE)
    assert resolve("${env:ARENA_TEST_SECRET}").reveal() == VALUE


def test_an_unset_variable_is_none_rather_than_an_error(monkeypatch):
    # A local or mock model needs no credential, so "nothing here" is a normal
    # answer the caller decides about — not a failure.
    monkeypatch.delenv("ARENA_TEST_SECRET", raising=False)
    assert resolve("${env:ARENA_TEST_SECRET}") is None


def test_a_bare_string_is_kept_as_a_literal_value():
    assert resolve(VALUE).reveal() == VALUE


def test_blank_and_none_references_resolve_to_nothing():
    assert resolve(None) is None
    assert resolve("   ") is None


def test_an_unknown_scheme_names_the_ones_that_work():
    with pytest.raises(SecretError) as exc:
        resolve("${vault:secret/data/openai}")
    message = str(exc.value)
    assert "vault" in message
    for scheme in ("env", "keyring", "file", "cmd"):
        assert scheme in message


# -------------------------------------------------------------- file scheme


def _write_key(path: Path, mode: int) -> Path:
    path.write_text(f"{VALUE}\n", encoding="utf-8")
    path.chmod(mode)
    return path


def test_file_reference_reads_and_strips(tmp_path):
    key = _write_key(tmp_path / "openai", 0o600)
    assert resolve(f"${{file:{key}}}").reveal() == VALUE


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_a_world_readable_key_file_is_refused_with_the_fix_in_the_message(tmp_path):
    key = _write_key(tmp_path / "openai", 0o644)
    with pytest.raises(SecretError) as exc:
        resolve(f"${{file:{key}}}")
    message = str(exc.value)
    assert str(key) in message
    assert "600" in message


def test_a_relative_file_reference_resolves_against_the_project_that_named_it(tmp_path):
    # Not against whatever directory the user happened to run `arena` from.
    _write_key(tmp_path / "key", 0o600)
    assert resolve("${file:key}", base_dir=tmp_path).reveal() == VALUE


def test_a_missing_key_file_is_none_rather_than_an_error(tmp_path):
    assert resolve(f"${{file:{tmp_path / 'absent'}}}") is None


# --------------------------------------------------------------- cmd scheme


def test_cmd_reference_captures_stdout():
    # The inner quoting must survive shlex.split, which is exactly how a real
    # credential helper invocation reaches this.
    got = resolve(f'${{cmd:{sys.executable} -c "print(\'{VALUE}\')"}}')
    assert got.reveal() == VALUE


def test_cmd_never_reaches_a_shell(tmp_path):
    """The security property of the whole module.

    A reference pasted from a vendor README may contain shell punctuation. If
    it were run through ``sh -c`` the second half would execute; here it must
    be passed through as an inert argument instead.
    """
    canary = tmp_path / "pwned"
    ref = f'${{cmd:{sys.executable} -c "print(1)" ; touch {canary}}}'
    try:
        resolve(ref)
    except SecretError:
        pass  # refusing outright is also a correct outcome
    assert not canary.exists()


def test_a_failing_command_reports_its_stderr():
    with pytest.raises(SecretError) as exc:
        resolve(f'${{cmd:{sys.executable} -c "import sys; sys.exit(3)"}}')
    assert "3" in str(exc.value)


def test_a_command_that_is_not_installed_says_so():
    with pytest.raises(SecretError) as exc:
        resolve("${cmd:definitely-not-a-real-binary-xyz read thing}")
    assert "PATH" in str(exc.value)


def test_an_empty_command_is_rejected():
    with pytest.raises(SecretError):
        resolve("${cmd:   }")


# ------------------------------------------------------------ provider keys


def test_provider_fallback_uses_the_same_table_as_the_connector_registry(monkeypatch):
    # If these two ever disagreed, a key that worked on the CLI would stop
    # working in the UI and nothing would say why.
    for kind, env_name in registry._API_KEY_ENVS.items():
        assert provider_env(kind) == env_name
        monkeypatch.setenv(env_name, VALUE)
        assert resolve_for_provider(kind).reveal() == VALUE


def test_an_explicit_reference_beats_the_conventional_variable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-convention")
    monkeypatch.setenv("ARENA_EXPLICIT", VALUE)
    assert resolve_for_provider("anthropic", "${env:ARENA_EXPLICIT}").reveal() == VALUE


def test_providers_that_need_no_credential_get_none():
    for kind in ("local", "ollama", "mock", "callable"):
        assert resolve_for_provider(kind) is None
