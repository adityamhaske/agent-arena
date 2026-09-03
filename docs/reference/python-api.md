# Python API

Using the arena as a library. Everything the CLI does is importable.

## Run an evaluation

```python
from agent_arena.core.runner import ArenaRunner

runner = ArenaRunner.from_project("projects/support_triage")
result = runner.run()

print(result.run_id, result.winner, result.total_cost_usd)
for entry in result.leaderboard.entries:
    print(entry.key, entry.status, entry.composite)
```

`RunResult` carries `run_id`, `project`, `config`, `test_cases`, `results` (every
`CallResult`), `leaderboard`, `duration_s` and `skipped_models`, plus `winner`,
`total_cost_usd` and `error_count`.

## Load and inspect a config

```python
from agent_arena.core.config import load_config

config = load_config("projects/support_triage")
print(config.project, len(config.models))
print(config.metrics.normalized_weights())
print(config.enabled_models)
```

`load_config` takes overrides matching the CLI flags:

```python
config = load_config("projects/support_triage", trials=5, models=["sim_small"])
```

## Progress callbacks

```python
def on_event(event):
    if event["event"] == "call_complete":
        print(f"{event['completed']}/{event['planned']}")

runner = ArenaRunner.from_project("projects/support_triage", progress=on_event)
runner.run()
```

Events: `run_start` (with `planned` and `skipped`), `call_complete` (with the
`CallResult`), `run_complete`.

## Re-score without re-running

```python
from agent_arena.core.metrics import build_leaderboard
from agent_arena.core.store import ResultStore

with ResultStore(config.database) as store:
    rows = store.results(run_id="run_20260902_162437_9b554f")

by_model = {}
for row in rows:
    by_model.setdefault(row["model_key"], []).append(row)

config.metrics.weights = {"accuracy": 0.8, "cost": 0.1, "latency": 0.1}
leaderboard = build_leaderboard(config, by_model, config.enabled_models, price_book)
```

This is exactly what the UI's what-if sliders do — no API calls, no spend.

## Query the store

```python
from agent_arena.core.store import ResultStore

with ResultStore("projects/support_triage/results/arena.sqlite") as store:
    for run in store.runs(project="support_triage", limit=10):
        print(run["run_id"], run["winner"], run["total_cost_usd"])

    for point in store.model_history("support_triage", "sim_small"):
        print(point["started_at"], point["composite"])

    for case in store.flaky_tests("support_triage"):
        print(case["test_id"], case["outcomes"])
```

`ResultStore` is a context manager. It is plain `sqlite3` — query the file
directly if that is easier.

## A custom scorer, programmatically

```python
from agent_arena.scorers import Scorer, ScoreResult
from agent_arena.scorers.registry import register_scorer

class MyScorer(Scorer):
    name = "my_scorer"
    def score(self, output, reference, context):
        return ScoreResult(score=1.0, passed=True)

register_scorer(MyScorer)
```

For a project, dropping the file in `scorers/` is simpler — it is discovered
automatically.

## A custom connector

```python
from agent_arena.connectors.base import Connector, GenerationResult
from agent_arena.connectors.registry import register_connector

class MyConnector(Connector):
    provider = "mine"
    def generate(self, request):
        return GenerationResult(text="...", model=self.model, provider=self.provider)

register_connector("mine", MyConnector)
```

Then `provider: mine` in config. Import the SDK **inside** `generate`, not at
module level — that is the lazy-import rule.

## Service layer

```python
from agent_arena.service import settings, secrets

settings.save({"theme": "dark"})
theme = settings.load()["theme"]

key = secrets.resolve("${env:OPENAI_API_KEY}")
if key:
    client = SomeSDK(api_key=key.reveal())   # .reveal() is the only way out
```

Never log or format a `Secret` — its `repr` and `str` are `***` precisely so an
accident is harmless.

## Errors

Everything raises a subclass of `ArenaError`:

```python
from agent_arena.core.errors import (
    ArenaError, ConfigError, TestCaseError, ScorerError, ConnectorError, HookError,
)
from agent_arena.service.errors import ServiceError, NotFoundError, ConflictError

try:
    runner.run()
except ConfigError as exc:
    print(f"fix your config: {exc}")
except ArenaError as exc:
    print(f"arena failed: {exc}")
```

Messages are written to point at the exact fix, so showing one to a user is
usually the right thing to do.
