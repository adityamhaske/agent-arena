# API keys and gateways

> **Status.** The `providers:` block parses and profiles resolve — that is tested
> in `tests/test_config_providers.py`. **The runner does not yet route through a
> profile**, so headers, custom CAs, proxies and model-prefix rewriting are not
> applied to a live call, and secret references are not yet consumed by a run.
> Today, credentials come from environment variables. This guide documents both,
> and says which is which. See [../roadmap/status.md](../roadmap/status.md).

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

## Working today: `.env` parsing

`agent_arena/core/env.py` is complete and tested. It reads
`~/.config/agent-arena/.env` and a project `.env`, with real environment
variables winning over file values.

```bash
# projects/my_project/.env
OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY="sk-ant-..."   # `export` prefix is accepted
# comments and blank lines are fine
```

**It is not yet wired into `cli.main()`**, so it has no effect on a real run yet.
`.env` is already in `.gitignore`.

## Designed: named provider profiles

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

## Designed: secret references

Never a literal key in config. `service/secrets.py` is complete and tested; **it
is not yet called by any command or by the runner**.

| Scheme | Resolves from |
|---|---|
| `${env:NAME}` | Environment |
| `${keyring:service/account}` | OS credential store |
| `${file:~/.secrets/openai}` | File contents; refuses a world-readable file |
| `${cmd:op read op://vault/item/field}` | Command stdout — 1Password, Vault, `aws secretsmanager` |

Resolved keys are wrapped in `Secret`, whose `repr` and `str` are `***`. See
[../security/secrets.md](../security/secrets.md).

## What to do now

1. Use environment variables. That is the path that works end to end.
2. Use `api_key_env` when you need two accounts today — a per-model variable is
   the v1 way to do what profiles will do properly.
3. Keep literal keys out of config regardless. A config snapshot is stored with
   every run, so a key in config also lands in your results database.
