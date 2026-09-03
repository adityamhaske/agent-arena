# Documentation

Agent Arena is two things in one repository: a **universal arena** that tells you
which model or pipeline to ship on your own criteria, and a **frozen study** on
whether splitting a task across agents loses information at the handoff. This
tree documents the arena; the study documents itself under
`studies/multi_agent_handoff/`.

## Start here

| If you are | Read |
|---|---|
| Evaluating models for the first time | [guides/quickstart.md](guides/quickstart.md) |
| Setting up your own project | [guides/your-first-project.md](guides/your-first-project.md) |
| Wiring in local models or a gateway | [guides/local-models.md](guides/local-models.md), [guides/api-keys-and-gateways.md](guides/api-keys-and-gateways.md) |
| Operating it day to day | [operations/](operations/README.md) |
| Contributing code | [../CONTRIBUTING.md](../CONTRIBUTING.md), [../AGENTS.md](../AGENTS.md), [architecture/](architecture/README.md) |
| Reviewing it for security | [security/](security/README.md) |
| Wondering what actually works yet | [roadmap/status.md](roadmap/status.md) |

## Sections

| Section | What it covers |
|---|---|
| [architecture/](architecture/README.md) | How the system is built: layers, the run lifecycle, the data model, scoring, metrics, connectors |
| [security/](security/README.md) | Threat model, credential handling, hardening, and why the engine has no dependencies |
| [design/](design/README.md) | UI and UX: the plain-language layer, information architecture, design system, interaction patterns, accessibility |
| [testing/](testing/README.md) | Test strategy, how to write one that fits, fixtures, and what CI actually checks |
| [reference/](reference/README.md) | Precise lookup: CLI, config schema, scorers, HTTP API, Python API, glossary |
| [guides/](guides/README.md) | Task-oriented walkthroughs, in a learning order |
| [operations/](operations/README.md) | Installing, running, controlling cost, storage, troubleshooting, performance |
| [roadmap/](roadmap/README.md) | What is shipped, what is planned, and what this deliberately will not become |
| [adr/](adr/) | Architecture decision records 0001–0011, spanning both systems |

## Also in this tree

- [UNIVERSAL_ARENA.md](UNIVERSAL_ARENA.md) — the original full reference for the arena
- [EXAMPLE_REPORT.md](EXAMPLE_REPORT.md) — what a finished run produces
- [DECISIONS.md](DECISIONS.md) — the ADR index
- [ROADMAP_10X.md](ROADMAP_10X.md) — the five-lever roadmap that shaped v1 and v2

## A note on accuracy

Every claim in this tree is meant to be true of the code as it exists now, not of
the plan. Roughly half of the v2.0 design is not built yet, and describing an
aspiration in the present tense would make the documentation actively harmful —
a reader cannot tell the difference. [roadmap/status.md](roadmap/status.md) is
the shipped-versus-planned table; when a page mentions something unbuilt, it says
so explicitly.
