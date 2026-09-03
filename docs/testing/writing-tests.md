# Writing tests

## The module docstring says *why*

Every test module opens by explaining what makes these tests worth having. From
`tests/test_web.py`:

```python
"""Tests for the browser UI's server side.

Two things are worth testing here and nothing else is:

* the **language layer**, because a wrong sentence in front of a non-technical
  user is worse than a raw number — they cannot tell it is wrong;
* the **API**, because it writes to the filesystem and spends money, and
  because a what-if that disagreed with a real run would quietly mislead.
"""
```

That is the model. It tells the next reader which risks the file is defending
against, which is what lets them judge whether a new test belongs in it.

## Name for behaviour

```python
# good — the name is the failure report
def test_a_world_readable_key_file_is_refused_with_the_fix_in_the_message(): ...
def test_soft_deleting_a_run_hides_it_from_history(): ...
def test_cmd_never_reaches_a_shell(): ...

# bad — tells you nothing when it goes red
def test_resolve_file_2(): ...
def test_delete(): ...
```

When a test fails in CI, its name is often all the reviewer sees. Make it a
sentence about the system.

## Isolation

**Never touch the developer's real environment.** Use `tmp_path` and
`monkeypatch`:

```python
def test_settings_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save({"theme": "dark"})
    assert load()["theme"] == "dark"
```

A test that writes to the real `~/.config` or leaks into `os.environ` poisons
every test after it, and the failure surfaces somewhere unrelated.

The same applies to the committed `projects/local_demo/results/arena.sqlite` —
copy it to `tmp_path` before touching it. It is a real artefact from a real run
and part of the documentation.

## Do not sleep

```python
# bad — adds real seconds to every run
def test_retry_backs_off():
    run_with_retries()

# good — inject a tiny backoff, or patch the clock
def test_a_retryable_error_is_attempted_the_configured_number_of_times(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    ...
```

Randomness gets the same treatment: `retry.sleep_for` takes a `random.Random`
as a parameter so tests can seed it, rather than reaching for the module-level
functions.

## Assert on the message when the message is the feature

Many of this project's errors exist to tell the user how to fix something. That
guidance is behaviour and deserves a test:

```python
def test_an_unknown_scheme_names_the_ones_that_work():
    with pytest.raises(ServiceError) as exc:
        resolve("${vault:secret/data/openai}")
    message = str(exc.value)
    assert "vault" in message
    for scheme in ("env", "keyring", "file", "cmd"):
        assert scheme in message
```

## Test the security property, not the implementation

```python
def test_cmd_never_reaches_a_shell(tmp_path):
    """The security property of the whole module."""
    canary = tmp_path / "pwned"
    ref = f'${{cmd:{sys.executable} -c "print(1)" ; touch {canary}}}'
    try:
        resolve(ref)
    except ServiceError:
        pass  # refusing outright is also a correct outcome
    assert not canary.exists()
```

This asserts the *outcome that matters* and stays true if the implementation
changes from `shlex.split` to something else. Asserting `shell=False` was passed
would test the code rather than the guarantee.

## Back-compat tests

Any change to a schema needs a test that old inputs still work:

```python
@pytest.mark.parametrize("name", ("support_triage", "doc_extraction",
                                  "pipeline_demo", "local_demo"))
def test_a_config_written_before_providers_existed_is_unchanged(name):
    config = load_config(f"projects/{name}")
    assert config.providers == []
    assert all(config.provider_for(spec) is None for spec in config.models)
```

The example projects are the canaries: they are real configs that real people
copy.

## `pytest` configuration

From `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_classes = ["*Tests"]                  # TestCase is a domain object, not a test class
filterwarnings = ["error::DeprecationWarning"]
```

`python_classes` matters: this project has a `TestCase` dataclass that pytest
would otherwise try to collect. And deprecation warnings are errors, so a
deprecated stdlib call fails the build rather than accumulating.

## Before you push

```bash
python3 -m pytest -q                                       # 526, all offline
arena validate --project projects/support_triage
arena evaluate --project projects/support_triage --quiet --no-report
arena evaluate --project projects/pipeline_demo  --quiet --no-report
python3 site/build.py && python3 site/check_links.py
```
