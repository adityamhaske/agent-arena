# Threat model

What this tool protects, what it does not, and why.

## Assets

| Asset | Where it lives | Impact if compromised |
|---|---|---|
| API keys | Environment, OS keyring, or `~/.config/agent-arena/secrets.json` (0600) | Direct financial loss; access to the user's provider account |
| API credit | Spent by any run | Financial loss without any credential leaving the machine |
| Project configs and test cases | `projects/<name>/` | May encode proprietary prompts, business rules, or customer data in cases |
| Run history | `results/arena.sqlite` | Model outputs, which may contain whatever the test inputs contained |
| The filesystem | Reachable by the local API | Arbitrary read and write within reach of the user's own permissions |

## Trust boundaries

```text
   ┌──────────────────────────── the user's machine ───────────────────────────┐
   │                                                                            │
   │   browser ──HTTP──▶ localhost:8420 ──▶ ArenaAPI ──▶ filesystem + sqlite    │
   │      ▲                (no auth)                                            │
   │      │                                                                     │
   │   any web page the user has open  ◀── the interesting boundary             │
   │                                                                            │
   │   project folder ──▶ scorers/*.py, hooks.py ──▶ executed in-process        │
   └────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼  HTTPS
                          model providers / local endpoints
```

The boundary that carries the most weight is the **browser**, because it is the
one thing on the machine that also talks to the open internet.

## Actor by actor

### A web page open in the user's browser

**Risk.** Any page can issue requests to `http://localhost:8420`. If it could
drive the API, it could read projects, exfiltrate model outputs, or start runs
that spend money.

**What the code does.**

- `ArenaHandler._host_allowed` checks the `Host` header against an allow-list
  (`localhost`, `127.0.0.1`, `::1`, and the bind host). This blocks DNS
  rebinding, where an attacker points a hostname they control at 127.0.0.1 to get
  a same-origin foothold.
- A `Content-Security-Policy` locks scripts to same-origin, with
  `frame-ancestors 'none'` and `base-uri 'none'`.
- `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`.
- No CORS headers are sent, so a cross-origin `fetch` cannot read responses.

**What it does not do, stated plainly.**

- **There is no CSRF token and no `Origin`/`Sec-Fetch-Site` check.** A
  cross-site form POST carries a legitimate `Host` header, so the rebinding
  allow-list does not cover it. Absence of CORS stops an attacker *reading* the
  response, but a state-changing POST can still fire.
- **A request with no `Host` header passes**, because `not host` short-circuits
  the check.

Both are known gaps rather than oversights, and both are on the hardening list.

### A process on the same host

Any local process running as the user can reach the API and read the config
directory. This is **out of scope**: a process running as you can already read
your environment, your files and your keyring. The tool does not attempt to
defend against an attacker who is already you.

### A hostile or compromised model endpoint

A model you point `api_base` at sees every prompt you send — including whatever
your test cases contain — and returns text you then store, render and possibly
execute.

- Output is stored and rendered. HTML export escapes everything with
  `html.escape`; an eval report that executed its own contents would be a bad
  look.
- Output reaches `code_exec` if a case uses that scorer. That is the sharp edge:
  see [hardening.md](hardening.md).
- The tool does not validate TLS beyond the defaults, and `verify_tls: false` on
  a provider profile disables checking entirely. That is your decision to make
  explicitly.

### A project folder from an untrusted source

**This is the highest-severity realistic risk, and it is out of scope by design.**

A project's `scorers/*.py` and `hooks.py` are imported and executed in-process,
with your permissions. A project folder is *code*, not data. Downloading someone
else's project and running `arena evaluate` on it is equivalent to running their
Python script.

Read a project folder before running it, exactly as you would a shell script.

### The network, when `--host` is not loopback

`arena ui --host 0.0.0.0` puts an unauthenticated API on the network. Anyone who
can reach the port can read and edit your projects, start runs against your keys,
and read every stored model output. The server prints this warning at startup
rather than quietly protecting you, because the alternative — refusing — would
break legitimate remote-development use.

A token-authenticated mode is designed but **not built**. Until it is, use an SSH
tunnel: see [hardening.md](hardening.md).

## Explicitly out of scope

- Multi-user isolation. There is one user.
- Authentication and authorization. There is no login by design.
- Protecting the user from their own project code.
- Sandboxing `code_exec`. It is process isolation, not a security boundary.
- Defending against a local process running as the user.

## Guards, summarised

| Guard | Where | Protects against |
|---|---|---|
| Host allow-list | `server.py::_host_allowed` | DNS rebinding |
| CSP, nosniff, no-referrer | `server.py::_send` | Injected markup, MIME confusion, referrer leakage |
| Static path containment | `server.py::_serve_static` | Path traversal to arbitrary files |
| `MAX_BODY_BYTES` (8 MB) | `server.py::_read_body` | Memory-exhaustion via a large body |
| `Secret` type | `service/secrets.py` | Credentials leaking into logs, reports and errors |
| 0600 file modes | `service/secrets.py`, `service/settings.py` | Other local users reading stored keys |
| Key-file mode check | `service/secrets.py::_require_private` | Silently accepting a world-readable key file |
| `shlex.split`, never `shell=True` | `service/secrets.py::_resolve_cmd` | Shell injection through a `${cmd:...}` reference |
