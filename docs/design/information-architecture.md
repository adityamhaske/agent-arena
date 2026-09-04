# Information architecture

## What ships today

Sixteen hash routes in `app.js` behind a sidenav grouped into Evaluate,
Reference and Configure. Built in vanilla JS: no framework, no build step, and
no dependency added to the install (invariant 2).

| Route | View | Purpose |
|---|---|---|
| `#/` | Home | Every project, with last-run summary |
| `#/new` | Wizard | Five steps: what is the job → name it → which models → what matters → your examples |
| `#/p/:name` | Project | Overview and entry point to the rest |
| `#/p/:name/run` | Run | Live progress, the result feed |
| `#/p/:name/results` | Results | Leaderboard, verdict, disqualifications |
| `#/p/:name/priorities` | Priorities | What-if sliders and constraints |
| `#/p/:name/examples` | Examples | Test cases, bulk paste |
| `#/p/:name/history` | History | Past runs and a trend sparkline |

### The wizard

Five steps, in the order someone actually thinks:

1. **What is the job?** Seven plain descriptions — "sort things into categories",
   "pull specific details out of text". Picking one selects the scorer, a starting
   prompt and initial weights via `language.preset_for_eval_type`.
2. **Name it.**
3. **Which models?** From the catalog, with which need a key marked.
4. **What matters?** Weights, budget, latency target, accuracy floor.
5. **Your examples.** Cases, with bulk paste.

The output is the same `config.yaml` a developer would have hand-written. The
wizard is a different *input* to the same contract, not a parallel system.

### What today's IA gets wrong

- **Everything is scoped to one project.** There is no cross-project view, so
  "what did I spend this week" cannot be answered.
- **No settings anywhere.** Keys come only from environment variables, and there
  is nowhere to see or change one.
- **No delete.** The API has no `DELETE` verb at all, so a project created by a
  typo is permanent.
- **A two-link topbar does not scale.** It works for eight routes and not for
  sixteen.

## The shell

As built:

```text
┌────────────────┬──────────────────────────────────────────────┐
│ ◆ Agent Arena  │  breadcrumb                  ⌘K   ◐   v2.0.0 │
├────────────────┼──────────────────────────────────────────────┤
│  Overview      │                                              │
│  Projects      │                                              │
│  Runs          │                  page body                   │
│  Compare       │                                              │
│  Models        │                                              │
│  Providers     │                                              │
│  Test cases    │                                              │
│  Scorers       │                                              │
│  Settings      │                                              │
│  Docs          │                                              │
├────────────────┤                                              │
│ ● run active   │                                              │
│   42/120 ·$0.31│                                              │
│   [Cancel]     │                                              │
└────────────────┴──────────────────────────────────────────────┘
```

| Route | Adds |
|---|---|
| `/` Overview | Cross-project: recent runs, spend this week, regressions, provider health |
| `/projects` | Search, tag filter, duplicate, archive, **delete** |
| `/p/:id` | Tabs — Setup, Cases, Models, Runs, Insights |
| `/runs` | Cross-project run list, filterable by model, status, date, cost |
| `/runs/:id` | Per-case × per-model grid, failure drill-down, cost breakdown, config snapshot |
| `/compare` | Run against run, model against model, per-case flip diff |
| `/models` | Catalog with price, context, features, `as_of` staleness banner |
| `/providers` | Profile CRUD, live connection test, model discovery |
| `/cases` | Cross-project corpus, import, dedupe, coverage |
| `/scorers` | The ten builtins with a live tester |
| `/settings/*` | Nine sub-pages |
| `/docs` | In-app, offline |

### Settings sub-pages

General · Providers & keys · Defaults · Budgets & safety · Pricing catalog ·
Storage & data · Appearance · Advanced · About.

The three that carry the most weight are **Providers & keys** (the only place a
credential is managed), **Budgets & safety** (spend caps and the kill switch),
and **Storage & data** (where deletion of everything lives, behind typed
confirmation).

### The persistent run pill

A run in progress stays visible from every route, with its progress, its
accumulated cost, and a cancel button. A spending event should not be something
you have to navigate back to in order to stop.

See [../roadmap/status.md](../roadmap/status.md) for what is actually built.
