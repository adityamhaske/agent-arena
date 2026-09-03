# Hardening

Practical guidance, and the sharp edges worth knowing about.

## Keep it on loopback

The default is `127.0.0.1` and it is the right choice. `arena ui` has no login
because it is a single-user local tool; loopback is what makes that safe.

```bash
arena ui                      # loopback, correct
arena ui --host 0.0.0.0       # unauthenticated API on your network
```

The server prints a warning for the second form rather than refusing, because
refusing would break legitimate remote-development use. But understand what it
means: anyone who can reach the port can read and edit your projects, start runs
that spend your API credit, and read every stored model output.

## Remote access: use a tunnel, not a bind

To reach the UI on a remote machine, forward the port instead of exposing it:

```bash
ssh -N -L 8420:localhost:8420 you@remote-box
# then open http://localhost:8420 locally
```

The server stays on loopback on the remote host. SSH provides the
authentication and the encryption, which is exactly the part the arena does not
implement. Token-authenticated binding is designed but not built — see
[../roadmap/status.md](../roadmap/status.md).

## `code_exec` is isolation, not a sandbox

The `code_exec` scorer runs generated code in a **subprocess**. That contains a
crash and an infinite loop. It does not contain anything malicious: the
subprocess runs as you, with your filesystem and your network.

- Use it for code you are grading from a model you control, on inputs you wrote.
- Do not use it on output from an untrusted endpoint.
- If you need a real boundary, run the whole evaluation inside a container or a
  VM with no credentials mounted.

## A project folder is code

`scorers/*.py` and `hooks.py` are imported and executed in-process. Running
`arena evaluate` on someone else's project folder is equivalent to running their
Python script.

```bash
# before running a project you did not write:
find projects/theirs -name '*.py' -exec cat {} +
```

This is out of scope by design — the extension mechanism *is* running your code —
but it is worth stating because a project folder looks like data and is not.

## File permissions

| Path | Expected mode |
|---|---|
| `~/.config/agent-arena/secrets.json` | 0600 |
| `~/.config/agent-arena/settings.json` | 0600 |
| Any `${file:...}` key file | 0600 |

The tool sets the first two and refuses to read a loose third. Check them if you
have restored a config directory from a backup, since archives frequently do not
preserve modes:

```bash
ls -l ~/.config/agent-arena/
chmod 600 ~/.config/agent-arena/*.json
```

## Keep keys out of configs

Use a reference, never a value:

```yaml
providers:
  - id: work
    kind: openai
    api_key: ${env:OPENAI_API_KEY}     # good
    # api_key: sk-...                  # never — this file gets committed
```

Config snapshots are stored with every run, so a literal key in config also ends
up in your results database and any export of it.

## Custom CAs and TLS

A gateway with an internal CA is a legitimate case:

```yaml
providers:
  - id: corp_gateway
    kind: openai_compatible
    base_url: https://gateway.corp.internal/v1
    verify_tls: /etc/ssl/corp-ca.pem     # load a CA bundle
```

`verify_tls: false` disables certificate verification entirely. It exists because
sometimes you genuinely need it against an internal endpoint with a self-signed
certificate, but it means anything on the path can read and alter your prompts
and your key. Prefer the CA bundle.

## Untrusted model endpoints

Everything you send reaches the endpoint, including whatever your test cases
contain. Before pointing `api_base` at a third-party gateway, check what your
cases actually hold — evaluation corpora are often built from production traffic
and carry real customer data.

## A pre-flight checklist

```bash
arena ui                                 # loopback, not --host
ls -l ~/.config/agent-arena/             # 0600 on both json files
grep -rn 'sk-\|api_key:' projects/       # no literal keys in configs
find projects/ -name '*.py' | xargs ls   # you wrote or reviewed all of these
git diff --cached | grep -iE 'sk-|token' # nothing secret staged
```
