# Credential handling

`agent_arena/service/secrets.py`. Two problems are solved here: getting a key
from where it lives to where it is needed, and stopping it leaking on the way.

## A credential is never a `str`

Resolved keys are wrapped in `Secret`:

```python
>>> s = Secret("sk-ant-api03-real-key")
>>> repr(s), str(s), f"{s}"
('***', '***', '***')
>>> json.dumps({"key": s}, default=str)
'{"key": "***"}'
>>> s.reveal()
'sk-ant-api03-real-key'
```

`Secret` deliberately does **not** subclass `str` — inheriting `str.__str__`
would give the leak straight back. `.reveal()` is the only way out, and its name
is chosen to be greppable: `grep -rn '\.reveal()'` shows every place a raw
credential is handled.

This is invariant 8 in [../../AGENTS.md](../../AGENTS.md). The rule extends
further: **no function returns a secret value in a dict**, only the reference
string. Those dicts get serialised into API responses and stored in run
snapshots.

## Reference schemes

Write a reference in config, never a value:

| Scheme | Resolves from |
|---|---|
| `${env:NAME}` | Process environment |
| `${keyring:service/account}` | OS credential store |
| `${file:~/.secrets/openai}` | File contents, trimmed. Refuses a group- or world-readable file |
| `${cmd:op read op://vault/item/field}` | Command stdout — 1Password, Vault, `aws secretsmanager` |
| *(no wrapper)* | A literal value, kept as given |

```yaml
providers:
  - id: work
    kind: openai
    api_key: ${env:OPENAI_API_KEY}
  - id: personal
    kind: openai
    api_key: ${keyring:agent-arena/openai-personal}
```

### Resolution order

For a model with no explicit reference, `resolve_for_provider(kind)` falls back
to the vendor's conventional variable — `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`GEMINI_API_KEY` — read from the **same table the connector registry uses**. If
those two ever disagreed, a key that worked on the CLI would stop working in the
UI with nothing to explain why. A test asserts they agree.

A reference that resolves to nothing returns `None` rather than raising. That is
not an error: local and mock models need no credential at all.

### Why `${cmd:}` never touches a shell

```python
argv = shlex.split(body)
subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
```

Credential-helper invocations get pasted out of vendor READMEs. If one were run
through `sh -c`, a `;` or a backtick in it would become something the arena
executes on your behalf. `shlex.split` with a list argv makes that inert, and a
test proves a reference containing `; touch <canary>` never creates the canary.

### Why a world-readable key file is refused

`${file:...}` raises `ServiceError` naming the file and the `chmod 600` fix when
the file is group- or world-readable. Silently reading it would teach the habit
that storing keys in loose files is fine.

## Where keys are stored

Preference order:

1. **OS credential store** — reached through the platform tool, not a Python
   dependency (invariant 1): `security` on macOS, `secret-tool` on Linux,
   PowerShell CredentialManager on Windows. `keyring_available()` probes with
   `shutil.which`.
2. **`~/.config/agent-arena/secrets.json`**, mode 0600, `chmod` applied
   explicitly after writing because the umask makes create-mode unreliable.
   Refused on read if the mode has since loosened.
3. **Environment variables**, including a `.env` file (`agent_arena/core/env.py`).
   Real environment variables win over file values, so an explicitly exported key
   always beats a stale file.

A key typed into a UI form is stored in the key store and only its
**reference** is persisted to `settings.json` — a raw key must never land in a
plaintext settings file.

## Redaction

`redact(text, secrets)` replaces revealed values with `***`. It is the last line
of defence for error messages that quote a request or echo a proxy response.
Values under 8 characters are skipped: blanking a two-character "secret" would
mangle unrelated prose without protecting anything a real key looks like.

## Runbooks

### Rotating a key

```bash
# 1. Issue the new key in the provider console, keep the old one live.
# 2. Update where it is stored:
security add-generic-password -U -s agent-arena -a openai-personal -w   # macOS, prompts
#    or update your shell profile / .env for ${env:...} references.
# 3. Prove it works:
arena validate --project projects/my_project
# 4. Revoke the old key in the provider console.
```

Nothing in a project config needs editing, because the config holds a reference,
not a value. That is the point of the indirection.

### If a key was committed to git

Assume it is compromised the moment it is pushed. Public repositories are
scraped within minutes.

```bash
# 1. REVOKE FIRST. Rotation before cleanup — history rewriting takes time and
#    the key is live the whole time.
# 2. Then remove it from history:
git log -S 'sk-' --oneline                    # find where it entered
# use git-filter-repo (preferred) or BFG to strip it, then force-push.
# 3. Every clone and fork still has it. Revocation is the only real fix.
```

Then move the key behind a reference so it cannot recur:

```yaml
api_key: ${env:OPENAI_API_KEY}   # not the value
```

`.gitignore` already covers `.env`. Check before committing:

```bash
git diff --cached | grep -iE 'sk-|api[_-]?key|secret|token'
```
