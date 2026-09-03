"""User settings: the store that lets `arena ui` remember anything.

These tests exist because this is the first file the tool writes *outside* a
project folder, and the ways that goes wrong are all quiet ones: a half-written
file after a crash, a preference silently dropped because a patch clobbered its
siblings, a typo saved as if it meant something, provider configuration left
world-readable, or — worst — a corrupt byte that locks the user out of their
own tool.

Every test redirects XDG_CONFIG_HOME at tmp_path. A test here that touches the
developer's real ~/.config is a bug in the test, not a bad day.
"""

from __future__ import annotations

import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from agent_arena.service import settings
from agent_arena.service.errors import ServiceError


@pytest.fixture(autouse=True)
def isolated_config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the whole module at tmp_path for every test in this file."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return tmp_path / "xdg"


def test_defaults_come_back_when_nothing_has_been_saved() -> None:
    assert not settings.settings_path().exists()

    loaded = settings.load()

    assert loaded == settings.DEFAULTS
    assert loaded["projects_dir"] == "projects"
    assert loaded["theme"] == "system"


def test_loading_does_not_hand_back_the_defaults_themselves() -> None:
    """A caller mutating what it loaded must not rewrite everyone's defaults."""
    loaded = settings.load()
    loaded["theme"] = "dark"
    loaded["budgets"]["on_exceed"] = "warn"

    assert settings.DEFAULTS["theme"] == "system"
    assert settings.DEFAULTS["budgets"]["on_exceed"] == "stop"


def test_a_saved_patch_round_trips() -> None:
    saved = settings.save({"theme": "dark", "projects_dir": "~/work/evals"})

    assert saved["theme"] == "dark"
    reloaded = settings.load()
    assert reloaded["theme"] == "dark"
    assert reloaded["projects_dir"] == "~/work/evals"


def test_a_nested_patch_leaves_its_siblings_alone() -> None:
    """This is what "deep merge" has to mean: setting one budget key must not
    wipe the other three."""
    settings.save({"budgets": {"max_run_usd": 12.5}})
    settings.save({"budgets": {"on_exceed": "warn"}})

    budgets = settings.load()["budgets"]
    assert budgets["max_run_usd"] == 12.5
    assert budgets["on_exceed"] == "warn"
    assert budgets["confirm_above_usd"] == settings.DEFAULTS["budgets"]["confirm_above_usd"]
    assert budgets["max_model_usd"] is None


def test_a_top_level_patch_leaves_unrelated_keys_alone() -> None:
    settings.save({"theme": "dark"})
    settings.save({"log_level": "debug"})

    loaded = settings.load()
    assert loaded["theme"] == "dark"
    assert loaded["log_level"] == "debug"
    assert loaded["defaults"] == settings.DEFAULTS["defaults"]


def test_a_list_setting_is_replaced_whole_not_merged() -> None:
    """Deleting a saved provider has to actually delete it, so lists replace."""
    settings.save({"providers": [{"id": "one"}, {"id": "two"}]})
    settings.save({"providers": [{"id": "one"}]})

    assert settings.load()["providers"] == [{"id": "one"}]


def test_a_corrupt_file_yields_defaults_and_is_preserved() -> None:
    path = settings.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"theme": "dark", oops', encoding="utf-8")

    loaded = settings.load()

    assert loaded == settings.DEFAULTS
    quarantined = path.with_name(path.name + settings.CORRUPT_SUFFIX)
    assert quarantined.exists(), "the broken file must be kept, not silently destroyed"
    assert quarantined.read_text(encoding="utf-8") == '{"theme": "dark", oops'
    assert not path.exists()


def test_a_json_file_that_is_not_a_mapping_is_also_quarantined() -> None:
    path = settings.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('["theme", "dark"]', encoding="utf-8")

    assert settings.load() == settings.DEFAULTS
    assert path.with_name(path.name + settings.CORRUPT_SUFFIX).exists()


def test_saving_after_a_corrupt_file_starts_from_defaults() -> None:
    path = settings.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json at all", encoding="utf-8")

    saved = settings.save({"theme": "light"})

    assert saved["theme"] == "light"
    assert saved["projects_dir"] == settings.DEFAULTS["projects_dir"]


def test_an_unknown_top_level_key_is_rejected_and_names_the_valid_ones() -> None:
    with pytest.raises(ServiceError) as excinfo:
        settings.save({"them": "dark"})

    message = str(excinfo.value)
    assert "them" in message
    assert "theme" in message, "a near-miss should be suggested"
    for key in settings.DEFAULTS:
        assert key in message
    assert not settings.settings_path().exists(), "a rejected patch writes nothing"


def test_an_unknown_key_alongside_a_valid_one_saves_neither() -> None:
    settings.save({"theme": "dark"})

    with pytest.raises(ServiceError):
        settings.save({"log_level": "debug", "not_a_setting": 1})

    assert settings.load()["log_level"] == settings.DEFAULTS["log_level"]


def test_unknown_keys_already_in_the_file_survive_a_load() -> None:
    """A file written by a newer arena must not lose keys to an older one."""
    path = settings.settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"theme": "dark", "from_the_future": 7}), encoding="utf-8")

    loaded = settings.load()

    assert loaded["from_the_future"] == 7
    assert loaded["theme"] == "dark"


def test_the_written_file_is_owner_only() -> None:
    """Saved provider profiles live here, so the file is not for other users."""
    settings.save({"theme": "dark"})

    mode = stat.S_IMODE(settings.settings_path().stat().st_mode)
    assert mode == 0o600, f"expected 0600, got {mode:04o}"


def test_the_written_file_is_still_owner_only_after_a_second_save() -> None:
    settings.save({"theme": "dark"})
    settings.save({"theme": "light"})

    assert stat.S_IMODE(settings.settings_path().stat().st_mode) == 0o600


@contextmanager
def crashing_at_the_final_rename() -> Iterator[None]:
    """Fail exactly at os.replace — the step that makes a write visible.

    Its own MonkeyPatch context, not the test's: undoing this must not also
    undo the XDG_CONFIG_HOME redirect the whole module depends on.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise OSError("no space left on device")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "replace", refuse)
        yield


def test_a_failed_write_leaves_the_previous_settings_intact() -> None:
    """No partial file is ever observable: the swap is a rename or nothing."""
    settings.save({"theme": "dark"})
    before = settings.settings_path().read_bytes()

    with crashing_at_the_final_rename(), pytest.raises(OSError):
        settings.save({"theme": "light"})

    assert settings.settings_path().read_bytes() == before
    assert settings.load()["theme"] == "dark"


def test_a_failed_write_leaves_no_stray_temp_file() -> None:
    settings.save({"theme": "dark"})

    with crashing_at_the_final_rename(), pytest.raises(OSError):
        settings.save({"theme": "light"})

    assert [p.name for p in settings.config_dir().iterdir()] == ["settings.json"]


def test_a_successful_write_leaves_no_stray_temp_file() -> None:
    settings.save({"theme": "dark"})
    settings.save({"log_level": "debug"})

    assert sorted(p.name for p in settings.config_dir().iterdir()) == ["settings.json"]


def test_reset_without_keys_restores_everything() -> None:
    settings.save({"theme": "dark", "budgets": {"max_run_usd": 9.0}})

    assert settings.reset() == settings.DEFAULTS
    assert settings.load() == settings.DEFAULTS


def test_reset_without_keys_removes_the_file_rather_than_pinning_defaults() -> None:
    settings.save({"theme": "dark"})

    settings.reset()

    assert not settings.settings_path().exists()


def test_reset_with_keys_leaves_the_others_alone() -> None:
    settings.save({"theme": "dark", "log_level": "debug"})

    result = settings.reset(["theme"])

    assert result["theme"] == settings.DEFAULTS["theme"]
    assert result["log_level"] == "debug"
    assert settings.load()["log_level"] == "debug"


def test_reset_replaces_a_nested_block_outright() -> None:
    """Merging cannot clear a nested value; reset has to, or a budget set once
    could never be taken back."""
    settings.save({"budgets": {"max_run_usd": 9.0, "on_exceed": "warn"}})

    budgets = settings.reset("budgets")["budgets"]

    assert budgets == settings.DEFAULTS["budgets"]
    assert budgets["max_run_usd"] is None


def test_reset_rejects_an_unknown_key() -> None:
    with pytest.raises(ServiceError, match="not a setting"):
        settings.reset(["theem"])


def test_xdg_config_home_is_honoured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    elsewhere = tmp_path / "somewhere-else"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(elsewhere))

    assert settings.config_dir() == elsewhere / "agent-arena"
    assert settings.settings_path() == elsewhere / "agent-arena" / "settings.json"

    settings.save({"theme": "dark"})
    assert (elsewhere / "agent-arena" / "settings.json").exists()


def test_xdg_config_home_is_read_on_every_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read at call time, not import time — otherwise nothing could redirect it."""
    first = tmp_path / "first"
    second = tmp_path / "second"

    monkeypatch.setenv("XDG_CONFIG_HOME", str(first))
    settings.save({"theme": "dark"})

    monkeypatch.setenv("XDG_CONFIG_HOME", str(second))
    assert settings.load() == settings.DEFAULTS

    monkeypatch.setenv("XDG_CONFIG_HOME", str(first))
    assert settings.load()["theme"] == "dark"


def test_falls_back_to_dot_config_when_xdg_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/tester")))

    assert settings.config_dir() == Path("/home/tester/.config/agent-arena")


def test_the_saved_file_is_readable_json() -> None:
    """The file is meant to be hand-editable; it must not be an opaque blob."""
    settings.save({"theme": "dark"})

    written = json.loads(settings.settings_path().read_text(encoding="utf-8"))

    assert written["theme"] == "dark"
    assert written["defaults"]["trials"] == settings.DEFAULTS["defaults"]["trials"]


def test_a_non_mapping_patch_is_rejected() -> None:
    with pytest.raises(ServiceError, match="mapping"):
        settings.save([("theme", "dark")])  # type: ignore[arg-type]
