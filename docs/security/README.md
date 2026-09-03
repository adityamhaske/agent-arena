# Security

Agent Arena is a **single-user local tool** that reads and writes your
filesystem, holds your API keys, and spends your money. It binds to loopback and
has no authentication, deliberately. Everything in this section follows from
that posture.

For the short public policy — supported versions and how to report a
vulnerability — see [../../SECURITY.md](../../SECURITY.md). These pages are the
detail behind it.

| Page | Covers |
|---|---|
| [threat-model.md](threat-model.md) | Assets, trust boundaries, actor-by-actor analysis, and the guards that actually exist |
| [secrets.md](secrets.md) | Credential references, the `Secret` type, the OS keyring, and key-rotation runbooks |
| [hardening.md](hardening.md) | Practical deployment guidance and the sharp edges |
| [dependency-policy.md](dependency-policy.md) | Why the engine has no dependencies, and the bar a new one must clear |

## The one-paragraph version

Run it on `localhost`. Do not pass `--host 0.0.0.0` unless you understand that it
puts an unauthenticated API that can edit your projects and spend your API credit
onto your network — the server prints that warning itself. Keep API keys in your
OS keyring or environment, never in a config file. Treat a project folder from
someone else as untrusted code, because `scorers/*.py` and `hooks.py` execute.
Do not use `code_exec` on output from a model you do not control.

## Reporting

Report privately through GitHub security advisories or the address in
[../../SECURITY.md](../../SECURITY.md). Please do not open a public issue for a
vulnerability.
