# Fixtures

`tests/conftest.py` is deliberately small. Two things, both about building a
project to test against.

## `write_project(...)`

A helper, not a fixture — call it directly when you need a project with specific
contents.

```python
from tests.conftest import write_project

def test_something(tmp_path):
    project = write_project(tmp_path, ...)
```

It writes a `config.yaml` and a `tests.yaml` into the directory you give it and
returns the path. Because it takes `tmp_path`, each test gets an isolated project
and nothing leaks between them.

Reach for it when the test is *about* a config shape — an unusual weights block,
a constraint that should disqualify, a scorer option.

## `simple_project` fixture

```python
@pytest.fixture()
def simple_project(tmp_path: Path) -> Path: ...
```

A ready-made minimal project. Request it as an argument when the test needs *a*
project rather than a particular one:

```python
def test_history_is_empty_before_any_run(simple_project):
    assert list_runs(simple_project.parent, simple_project.name) == []
```

## Choosing between them

| Situation | Use |
|---|---|
| The config's contents are what you are testing | `write_project` |
| You just need something valid to run against | `simple_project` |
| You need several projects (listing, duplication, deletion) | `write_project`, called repeatedly |

## Building on the example projects

For behaviour that should hold against a real config, load one of the committed
examples rather than inventing a new one:

```python
config = load_config("projects/support_triage")
```

They are offline, deterministic, and already exercised by CI. This is what the
back-compat tests do — the point is precisely that these are configs real people
copied.

Never mutate them from a test. Copy into `tmp_path` first:

```python
import shutil

def test_migration_upgrades_a_real_database(tmp_path):
    src = Path("projects/local_demo/results/arena.sqlite")
    db = tmp_path / "arena.sqlite"
    shutil.copy(src, db)
    ...
```

That database is a committed artefact from a real run, and it is the only
realistic migration fixture in the repo.

## Fixtures deliberately absent

| Not provided | Why |
|---|---|
| A mock HTTP provider | `mock:` models cover it at the connector layer, offline and faster |
| A fake API key | Tests use `mock:` models, which need no credential |
| A shared database | Per-test `tmp_path` databases keep tests independent and parallelisable |

`tests/test_local_connector.py` stands up a real local HTTP server for the cases
that genuinely need one. Reuse that approach rather than adding a global fixture
— it keeps the cost where it is needed.
