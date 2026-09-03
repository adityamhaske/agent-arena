# API keys and gateways

> **Status.** Provider profiles route for real: the endpoint, credential,
> headers, TLS setting, proxy, timeout and model-prefix rewrite are all applied
> to a live call, asserted against a recording server in
> `tests/test_provider_routing.py`. Per-provider *rate limits* parse but are not
> yet enforced. See [../roadmap/status.md](../roadmap/status.md).

## Today: environment variables

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export GEMINI_API_KEY="..."
arena evaluate --project projects/my_project
```

Per model:

```yaml
models:
  - key: work_gpt
    model: gpt-5
    api_key_env: WORK_OPENAI_KEY      # a different variable
```

A model whose key is missing is **skipped, not failed** — the run continues and
the leaderboard reports the skip with its reason.

## `.env` files

`agent_arena/core/env.py` is complete and tested. It reads
`~/.config/agent-arena/.env` and a project `.env`, with real environment
variables winning over file values.

```bash
# projects/my_project/.env
OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY="sk-ant-..."   # `export` prefix is accepted
# comments and blank lines are fine
```

Loaded in `cli.main()` before any command reads a credential. `.env` is already
in `.gitignore`.

## Named provider profiles

The capability this exists for: **two API keys for the same vendor in one run**,
which v1 could not express at all.

```yaml
providers:
  - id: work
    kind: openai
    api_key: ${env:WORK_OPENAI_KEY}
    headers: {OpenAI-Organization: org-123}
    rate_limit: {rpm: 500, tpm: 200000, concurrency: 4}

  - id: personal
    kind: openai
    api_key: ${keyring:agent-arena/openai-personal}

models:
  - key: gpt5_work
    provider: work
    model: gpt-5
  - key: gpt5_personal
    provider: personal
    model: gpt-5
```

Both entries are the same model on different accounts, competing in one run.

### A corporate gateway

```yaml
providers:
  - id: corp_gateway
    kind: openai_compatible
    base_url: https://gateway.corp.internal/v1
    api_key: ${keyring:agent-arena/corp}
    headers: {X-Portkey-Config: cfg_abc}
    verify_tls: /etc/ssl/corp-ca.pem      # private CA
    proxy: http://squid.corp:3128
    model_prefix: "openai/"               # rewrite ids on the way out
    timeout_s: 60
```

Works with LiteLLM proxy, Portkey, Cloudflare AI Gateway, a Bedrock proxy, or
anything else speaking the OpenAI API.

`verify_tls: false` disables certificate checking entirely. Prefer the CA bundle;
see [../security/hardening.md](../security/hardening.md).

### Back-compatibility

`provider:` naming a bare vendor kind (`anthropic`, `openai`, …) keeps its v1
meaning — `ProjectConfig.provider_for()` returns `None` and the existing registry
handles it. Only an id declared in `providers:` changes resolution. Every config
written before this block existed behaves identically, asserted for all four
example projects.

## Secret references

Never a literal key in config. The connector registry resolves the reference
when it builds the connection, so no caller ever holds the raw value.

| Scheme | Resolves from |
|---|---|
| `${env:NAME}` | Environment |
| `${keyring:service/account}` | OS credential store |
| `${file:~/.secrets/openai}` | File contents; refuses a world-readable file |
| `${cmd:op read op://vault/item/field}` | Command stdout — 1Password, Vault, `aws secretsmanager` |

Resolved keys are wrapped in `Secret`, whose `repr` and `str` are `***`. See
[../security/secrets.md](../security/secrets.md).

## Managing profiles from the CLI

```bash
arena providers add work --kind openai --api-key '${env:OPENAI_API_KEY}'
arena providers add gw --kind openai_compatible \
    --base-url https://gateway.corp.internal/v1 \
    --api-key 'sk-...' --header 'X-Portkey-Config=cfg_abc'
arena providers list
arena providers test gw          # can we reach it, and how fast
arena providers discover gw      # what models does it serve
arena providers rm gw --purge-key
```

A **literal** key passed to `providers add` is moved into your OS keyring and
only the reference is written to `settings.json`. That file is mode 0600 and
never holds a credential.

```bash
arena secrets set my-account     # prompts, or reads stdin
arena secrets get my-account     # prints *** unless --reveal
arena secrets rm my-account
```

## Keep literal keys out of config

A config snapshot is stored with every run, so a key pasted into `config.yaml`
also lands in your results database and in any export of it. Exports scrub
anything key-shaped on the way out, but the database still has it.
