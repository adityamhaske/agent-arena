<!--
Title this PR the way you would write the commit: `feat(scope): what changed`.
See CONTRIBUTING.md for the conventions and the full pre-push checklist.
-->

## What changed



## Why

<!-- The diff shows what. This section is for why — the problem, not the patch. -->

## How it was verified

<!-- Commands you ran and what they printed. Paste the number, not "tests pass". -->

```
python3 -m pytest -q
```

## Checklist

- [ ] `python3 -m pytest -q` is green — **526 passed** or more, and no test was
      skipped, disabled or quarantined to get there.
- [ ] **No new dependency.** Nothing added to `pyproject.toml`'s `dependencies`,
      nothing added to `agent_arena/web/` (no npm, no CDN, no build step), and
      every provider SDK still imports lazily. The test suite passes with no
      provider SDK installed.
- [ ] **No fabricated number.** Any price, accuracy figure or example output in
      the code, the docs or the README comes from a real run or a sourced price
      list — linked here. Unsourced is left absent, never estimated.
- [ ] **Rankings still come from `core/metrics.build_leaderboard`.** The UI
      re-words the engine's answer; it does not compute its own.
- [ ] The example projects still validate and run offline:
      `arena validate --project projects/support_triage` and
      `arena evaluate --project projects/support_triage --quiet --no-report`.
- [ ] Docs updated if behaviour changed. If `docs/` or `site/` was touched,
      `python site/build.py && python site/check_links.py` passes.
- [ ] Breaking change to the `config.yaml` schema, the `Scorer`/`Connector`
      contracts or CLI flags? Say so here — those are covered by semver
      (`CHANGELOG.md` → *Stability*).
