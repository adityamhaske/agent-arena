# Roadmap

| Page | Covers |
|---|---|
| [status.md](status.md) | **Shipped, partial or planned** — every capability, derived from the code |
| [future-updates.md](future-updates.md) | What is coming, grouped by theme, with the problem each solves |
| [non-goals.md](non-goals.md) | What this deliberately will not become, and why |

## Where things stand

Version 1.0.0 shipped a complete engine: config-driven projects, ten scorers, six
connectors, weighted composites with hard constraints, SQLite storage, a CLI, and
a browser UI.

Work toward 2.0 is partly done. The launch blockers are closed — there is a
licence, a security policy, a release workflow — and four correctness defects are
fixed. The service layer has its foundation: credential handling, user settings,
and the `providers:`/`budgets:` config blocks.

The largest remaining piece is the one most visible to a user: the multi-page
interface with a sidenav, settings, and delete. None of that is built.

[status.md](status.md) is the honest table. Read it before relying on anything
described elsewhere in the documentation as planned.

## Two older roadmap documents

- [../ROADMAP_10X.md](../ROADMAP_10X.md) — the five-lever roadmap. Levers 1 and 2
  (the browser UI, pipeline targets) shipped; 3, 4 and 5 have not.
- [../superpowers/plans/2026-09-02-agent-arena-v2-launch.md](../superpowers/plans/2026-09-02-agent-arena-v2-launch.md)
  — the full v2 plan: nine phases, the verified gap analysis, and the
  architecture decisions behind the current work.
