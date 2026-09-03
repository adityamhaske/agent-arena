# Test strategy

## The offline-first rule

Every test runs with no network, no API key, and no provider SDK installed.

This is enforced, not merely encouraged: the CI test job installs
`pip install -e ".[dev]"` and nothing else. If the suite ever needs `anthropic`
present to pass, invariant 1 has been broken and the build fails. That is the
whole point of the job.

### How you test a probabilistic system deterministically

You do not test the model. You test everything around it.

`mock:` models have fixed accuracy, latency and price, and produce stable
pseudo-random outcomes keyed on `(model, test, trial)`:

```yaml
models:
  - key: sim_small
    model: mock:small
    card: {input_usd_per_mtok: 1, output_usd_per_mtok: 5}
```

`mock:small` gets a known fraction right, at a known latency, at a known price.
So assertions like "this model is disqualified for missing the accuracy floor",
"the composite is X under these weights", and "cost is nulled when one model is
unpriced" become exactly repeatable.

This is also why the four example projects run in CI: they are documentation, and
a documented example that no longer produces its documented output is a lie the
build should catch.

## What is tested

| Layer | Module | What matters |
|---|---|---|
| Config | `test_config`, `test_config_providers` | Parse errors name the position and the fix; v1 configs are untouched by v2 additions |
| Test cases | `test_testcase` | Loading, filtering, per-case overrides |
| Scorers | `test_scorers` | Each eval type's behaviour and its edge cases |
| Metrics | `test_metrics` | The four normalization modes, weighting, constraints, disqualification, resolution guards |
| Connectors | `test_connectors`, `test_local_connector`, `test_callable_targets` | The contract, provider inference, a real HTTP server for local endpoints |
| Retry | `test_retry` | Classification, jitter bounds over many seeded draws, `Retry-After` in both forms |
| Storage | `test_store` | Round-trips and history queries |
| Runner | `test_runner` | Preflight skipping, concurrency, the abort path |
| Service | `test_service_secrets`, `test_service_settings` | Redaction, atomicity, permissions |
| Pricing | `test_pricing_catalog` | Cross-vendor resolution, aliases, sourced-or-absent |
| CLI | `test_cli` | Command surface and exit codes |
| Web | `test_web`, `test_web_jobs` | The API over real HTTP, and the sentences the language layer produces |

### Testing sentences, not just numbers

`test_web.py`'s docstring states the reasoning:

> the **language layer**, because a wrong sentence in front of a non-technical
> user is worse than a raw number — they cannot tell it is wrong

So the suite asserts on rendered wording, not only on the values behind it. A
stakeholder reading "costs 6¢ per 1,000 uses" has no way to check it.

## What is deliberately not tested

| Not tested | Why |
|---|---|
| Real provider APIs | Non-deterministic, costs money, needs credentials. The contract is tested against mocks; the SDK is the vendor's to test |
| Model quality | Not the tool's job. The tool measures; it does not decide what a good answer is |
| The docs site rendering | `site/check_links.py` checks links; visual output is reviewed by eye |
| Browser rendering | No headless browser, because that would be a dependency. The API is tested over real HTTP; the JS is reviewed |
| Accessibility | No automated check yet. See [../design/accessibility.md](../design/accessibility.md) |

## Rules

1. **Never skip, disable or quarantine a test to get CI green.** A quarantined
   test is a bug with a hiding place. Fix it or delete it deliberately.
2. **Name tests for behaviour, not for the function called.**
   `test_a_world_readable_key_file_is_refused_with_the_fix_in_the_message`, not
   `test_resolve_file_2`. The name should tell you what broke.
3. **The module docstring says why these tests exist**, not what they cover.
4. **A bug gets a regression test.** That is what `test_review_regressions.py` is.
5. **Keep it fast.** Twelve seconds is a feature. A test that sleeps for real, or
   reaches the network, costs everyone every run.
