# Testing

**472 tests, 12 seconds, fully offline, no API key, no provider SDK.**

That combination is a feature, not an accident. A suite you can run on every save
removes every excuse not to run it, and one that needs no credentials means a
contributor's first `pytest` succeeds instead of erroring on a missing key.

```bash
pip install -e ".[dev]"
python3 -m pytest -q          # 472 passed in ~12s
```

| Page | Covers |
|---|---|
| [strategy.md](strategy.md) | What is tested, what deliberately is not, and why offline-first works |
| [writing-tests.md](writing-tests.md) | Conventions, with real examples from the suite |
| [fixtures.md](fixtures.md) | `conftest.py` and how to build a project fixture |
| [ci.md](ci.md) | What the three workflows actually check |

## The suite

| Module | Tests | Protects |
|---|---|---|
| `test_retry.py` | 57 | Terminal vs retryable classification, jitter bounds, `Retry-After` |
| `test_web.py` | 41 | The plain-language layer and the JSON API |
| `test_scorers.py` | 35 | All ten builtin eval types |
| `test_connectors.py` | 35 | The connector contract and provider inference |
| `test_env.py` | 30 | `.env` parsing, quoting, precedence |
| `test_service_settings.py` | 27 | Settings merge, atomicity, corruption recovery |
| `test_pricing_catalog.py` | 26 | Cross-vendor price resolution and aliases |
| `test_metrics.py` | 26 | Normalization, weighting, constraints, disqualification |
| `test_service_secrets.py` | 24 | Redaction, reference schemes, no-shell guarantee |
| `test_callable_targets.py` | 24 | `run:` pipeline targets |
| `test_cli.py` | 22 | Every command's surface |
| `test_runner.py` | 20 | Preflight, concurrency, failure handling |
| `test_local_connector.py` | 20 | OpenAI-compatible endpoints, against a real local server |
| `test_review_regressions.py` | 19 | Specific bugs, so they cannot return |
| `test_testcase.py` | 18 | Case loading and filtering |
| `test_config_providers.py` | 17 | `providers:`/`budgets:` and v1 back-compat |
| `test_config.py` | 16 | Config parsing and validation |
| `test_web_jobs.py` | 9 | Job retention and cancellation |
| `test_store.py` | 6 | SQLite round-trips |

`test_review_regressions.py` is worth calling out: every test in it exists
because something was once broken. A bug that gets a test never comes back
silently.
