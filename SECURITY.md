# Security policy

Agent Arena is a local developer tool. It reads and writes a folder on your
disk, imports Python you put in that folder, and spends money against your API
keys. This document says exactly what that means, which guards exist in the
code, and which do not — so you can decide where to run it. Nothing here is
aspirational: every protection named below is one you can go read.

## Supported versions

| Version | Supported |
|---|---|
| 1.x (latest minor) | Yes — security fixes land here |
| Any earlier 1.x minor | No |
| Pre-1.0 | No |

Only the **latest published minor** gets fixes. There are no backports to older
minors: a fix ships as a new patch release on the current minor, and upgrading
is the remedy. Released versions are listed in
[CHANGELOG.md](CHANGELOG.md).

## Reporting a vulnerability

Please report privately. Do not open a public issue for something exploitable.

- **Preferred:** [GitHub private security advisories](https://github.com/adityamhaske/agent-arena/security/advisories/new)
- **Email:** daddysmail069@gmail.com

Useful reports include the version (`arena --version`), how the tool was
invoked (particularly the `arena ui` flags), a minimal reproduction, and what an
attacker gets out of it.

**What you can expect:** an acknowledgement within **7 days**. That is the only
timing commitment made here, because it is the only one that can be kept — this
is a small project with one maintainer, not a funded security team. After the
acknowledgement you will get an assessment of whether it is in scope (see the
threat model below) and, if it is, a fix in the next patch release with credit
in the changelog unless you would rather not be named.

**Never include a real API key, an `.env` file, or a `results/arena.sqlite`
from a real run in a report.** Redact them first. See
[API keys and secrets](#api-keys-and-secrets).

## Threat model

The security posture follows from one design decision, stated in
`agent_arena/web/server.py`: this is a **single-user local tool**, and the
person driving the browser is assumed to be the person who owns the machine,
the projects folder and the API keys.

### `arena ui` binds to loopback and has no authentication

There is no login, no session, no user model, and no per-request token. This is
deliberate, not an oversight. The UI drives the local filesystem and can start
runs that call paid APIs, so an authenticated remote version of it would be a
different product with a different set of promises. Instead it binds to
`127.0.0.1` by default and stays there.

Anyone who can reach the HTTP port can do everything the UI can do:

- create projects under the projects directory and overwrite the configuration
  of existing ones (`POST /api/projects`, `PUT /api/projects/{name}`)
- rewrite a project's test cases (`PUT /api/projects/{name}/tests`)
- start an evaluation run that calls model providers with your keys and spends
  real money (`POST /api/projects/{name}/run`)
- read every stored run, including every prompt and every model response
  (`GET /api/projects/{name}/history`, `/result`)

On loopback, "anyone who can reach the port" means any local process and any
page in any browser on that machine. That is the boundary the tool assumes.

### Passing a non-loopback `--host` is an explicit user decision

```bash
arena ui --host 0.0.0.0        # now on your network, still with no login
```

This puts the unauthenticated API above onto the network. The tool does not
refuse, and it does not quietly pretend to protect you — `serve()` prints:

```
WARNING: this is bound to a non-loopback address and has no login.
Anyone who can reach it can edit your projects and spend your API credit.
```

and `arena ui --help` says the same on the `--host` flag. Doing it anyway is
supported, and the consequences are yours: put it behind a reverse proxy that
terminates TLS and authenticates, or behind a VPN, or do not do it. A report
that amounts to "`--host 0.0.0.0` exposes the API" is working as designed and
documented; a report that a *loopback* bind is reachable from elsewhere is a
real bug.

### The guards that do exist

These are the only server-side protections in the code, and they exist to keep
an accident from becoming a remote shell — not to make the API safe to expose.

**Host allow-list against DNS rebinding** — `ArenaHandler._host_allowed`.
Without it, a page on the open internet could point a hostname it controls at
`127.0.0.1` and drive this API through the visitor's own browser, since the
browser would happily connect to loopback. Each request's `Host` header is
lowercased, stripped of its port and of `[]` brackets, and must be in the
allow-list built by `build_app`: `localhost`, `127.0.0.1`, `::1`, `0.0.0.0`,
plus whatever `--host` was passed. Anything else gets `403`. Accurately: a
request that sends **no** `Host` header at all is also allowed through, so this
stops browsers, not a raw socket client already on the machine.

**Security headers on every response** — `ArenaHandler._send`.
`Content-Security-Policy` with `default-src 'self'`, `script-src 'self'`
(scripts are same-origin only, which is the directive that matters against
injected markup), `frame-ancestors 'none'`, `base-uri 'none'` and
`form-action 'none'`. `style-src` permits `'unsafe-inline'` because bars and
progress meters set their width from data, and `img-src` permits `data:` for
the favicon. Also `X-Content-Type-Options: nosniff` and
`Referrer-Policy: no-referrer`.

**Static path containment** — `ArenaHandler._serve_static`. A request path is
joined to the package's `static/` directory and `resolve()`d; if the result is
not under `static/` or is not a regular file, the request is answered with the
app shell (`index.html`) so client-side routing survives a refresh. So
`GET /../../etc/passwd` returns the UI's HTML, not a file. The containment test
is a string-prefix comparison on the resolved path, which is exact here only
because `static/` is a directory inside the installed package with nothing
beside it sharing its name prefix.

**Project names cannot escape the projects directory** — `ArenaAPI._project_dir`
matches every name against `^[a-z0-9][a-z0-9_-]{0,63}$`, which admits no path
separators and no `..`, and then re-checks that the resolved path's parent is
the projects directory. The check is made twice on purpose.

**Request body cap** — `MAX_BODY_BYTES` (8 MiB) in
`agent_arena/web/server.py`. A declared `Content-Length` above it is rejected
with `413` before anything is read, so a hostile body cannot be turned into
memory pressure. This is a cap on the declared length; there is no separate
streaming limit.

**No CORS.** The server emits no `Access-Control-Allow-Origin` and implements
no `OPTIONS` handler, so another origin's page cannot read a response from this
API.

### Known limitations, stated plainly

- **No CSRF defence.** There is no per-request token and no `Origin` or
  `Sec-Fetch-Site` check. The `Host` allow-list does not help here, because a
  cross-site form posting to `http://localhost:8420/…` sends a legitimate
  `Host: localhost`. No CORS means the attacking page cannot *read* the reply,
  but a state-changing request — create a project, overwrite tests, start a
  paid run — can still be triggered while the UI is running. This is the one
  gap in the same class as the rebinding guard, and it is written down rather
  than glossed over.
- **No rate limiting and no request logging by default.** `--verbose` turns
  request logging on; without it the server is quiet so that polling does not
  bury real output.
- **The API is not hardened against a hostile local process.** Anything running
  as your user can already read your keys from the environment; the UI is not a
  boundary against it and does not try to be.

## Out of scope

These are accepted consequences of what the tool is. Reports about them will be
closed as working-as-designed, though a documentation gap is always worth
raising.

**Project code is trusted by design.** A project may declare
`scorers/*.py` and `hooks.py`, and `core/loaders.load_module_from_path` imports
them with `importlib` — which executes them, in your process, with your
privileges. That is the point: they are *your* code, the documented escape
hatch for scoring and preprocessing the built-ins do not cover. There is no
sandbox and there will not be one, because a sandbox that could run arbitrary
project scoring logic would be a container, and you already have one.

The practical rule: **a project folder is executable code. Read a project
folder from an untrusted source before you run it**, exactly as you would read
a `Makefile` or a `setup.py` before running it. Running an unread project from
a stranger is not a vulnerability in Agent Arena.

**Pointing the tool at a hostile model endpoint.** `api_base` accepts any URL,
including plain HTTP, and `LocalConnector` sends `Authorization: Bearer <key>`
whenever a key is configured. Aim a model at an endpoint you do not control and
you have handed that endpoint your prompts, your test data, and any key
attached to that model. That is a configuration decision, not a flaw — the
feature exists so Ollama, LM Studio, llama.cpp and vLLM work without a vendor
SDK.

**Model output is untrusted input, and is treated as data.** Responses are
scored and stored, never executed — *except* by the `code_exec` scorer, which
does exactly what its name says. `CodeExecScorer` writes model-generated code
to a temporary directory and runs it in a subprocess with a timeout. Its
docstring carries the warning and it bears repeating here: **a timeout and a
scratch working directory are not a sandbox.** If you are grading code from a
model you do not trust, run the whole arena in a container.

**Third-party provider SDKs.** `anthropic`, `openai`, `google-generativeai` and
`litellm` are optional extras that import lazily and are never installed by the
base package. Vulnerabilities in them belong to their maintainers; report them
upstream. Report to us anything about *how* Agent Arena calls them.

## API keys and secrets

**Keys live in environment variables. Agent Arena never writes one to disk, and
a key never belongs in `config.yaml`.**

`connectors/registry.py` resolves a key at connector-construction time from the
environment: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, or
whatever a model's `api_key_env` names. `config.yaml` holds the *name* of the
environment variable, never its value — so a project folder is safe to commit
and safe to share.

The rule, for anything that leaves your machine:

- **Never** paste a key into a bug report, a security report, a GitHub issue, a
  discussion, or a pull request.
- **Never** commit a `.env`, a shell profile, or a CI secret to a project
  folder.
- Before attaching a run to anything, check it. `results/arena.sqlite` and the
  generated `report.md` / `results.json` store **every prompt and every model
  response in full**. If a test case, a system prompt or a hook put a
  credential into a prompt, it is in those files. The arena does not redact
  them, because it cannot reliably tell a secret from a test fixture — and
  guessing would be fabricating.
- If you believe a key has been exposed, rotate it at the provider first. That
  is faster and more complete than anything this project can do for you.
