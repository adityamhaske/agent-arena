# Design

The people who decide which model to ship — who owns the support queue, who sets
the budget, who signs off on latency — are usually not the people who write YAML.
The browser UI exists for them. That single observation drives every decision in
this section.

## Two surfaces, clearly separated

Every page here distinguishes **what ships today** from **what is designed but
not built**. Today's UI is a 1,030-line vanilla-JS single-page app with eight
hash routes behind a two-link topbar. The v2 design — a sidenav shell, sixteen
routes, nine settings sub-pages, delete everywhere — is specified and approved
but not implemented. See [../roadmap/status.md](../roadmap/status.md).

| Page | Covers |
|---|---|
| [ux-principles.md](ux-principles.md) | The principles the shipped UI already follows, and the code that proves each |
| [plain-language.md](plain-language.md) | `web/language.py` — turning scores into sentences, and how to write new copy |
| [information-architecture.md](information-architecture.md) | Today's eight routes; the planned sixteen |
| [design-system.md](design-system.md) | The actual tokens, scales and responsive rules in `app.css` |
| [interaction-patterns.md](interaction-patterns.md) | Destructive actions, progress, cancellation, empty states |
| [accessibility.md](accessibility.md) | What is there, and the bar new work must meet |

## Constraints that shape the UI

The UI adds **no dependency** — `http.server` plus vanilla JS and CSS. No Flask,
no npm, no CDN, no build step (invariant 2). That is why there is no component
framework and why `app.css` is hand-written custom properties rather than a
utility library.

The UI **never re-implements the engine** (invariant 3). Rankings come from
`core/metrics.build_leaderboard`; `web/language.py` only re-words them. If the UI
and the CLI ever disagree about who won, the CLI is right and the UI has a bug.
