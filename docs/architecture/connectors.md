# Connectors

`agent_arena/connectors/` — the uniform model interface and the price book.

## The contract

Every provider looks the same to the runner: hand it a `GenerationRequest`, get a
`GenerationResult`. Adding a provider means implementing one method.

```python
class Connector(ABC):
    provider: str
    @abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationResult: ...
```

`GenerationRequest` carries `messages`, `system`, `max_tokens`, `temperature`,
provider-specific `params`, and `metadata` — bookkeeping such as the test id,
never sent to a real provider. Its `prompt` property flattens the message list
for providers and scorers that want one string.

`GenerationResult` carries the text plus what it cost to produce: token counts,
cache read/write tokens, `latency_ms`, `finish_reason`, and two fields worth
calling out:

- **`cost_usd`** — what this call *actually* cost, when the connector knows
  better than the catalog. A pipeline target knows its real end-to-end spend
  across every internal call; the price book cannot. When set, the runner trusts
  it over the catalog.
- **`metrics`** — extra numbers the connector measured, weightable in
  `metrics.weights` by name exactly like a builtin.

## The six connectors

| Provider | Class | Notes |
|---|---|---|
| `anthropic` | `AnthropicConnector` | Streams above 16,000 output tokens to avoid an SDK HTTP timeout. Drops `temperature` for model families that reject it, since sending it turns a working config into a 400 |
| `openai` | `OpenAIConnector` | Configurable token parameter (`max_completion_tokens` by default) and a `send_temperature` switch for models that refuse it |
| `gemini` | `GeminiConnector` | Maps `assistant` to `model` roles |
| `litellm` | `LiteLLMConnector` | The escape hatch — anything LiteLLM can reach, via `bedrock/…`, `together_ai/…`, `azure/…` |
| `local` | `LocalConnector` | Ollama, LM Studio, vLLM, llama.cpp — any OpenAI-compatible endpoint. Built on `urllib`, so evaluating a model on your own laptop needs no SDK at all |
| `mock` | `MockConnector` | Deterministic, offline, with fixed accuracy/latency/price |
| `callable` | `CallableConnector` | A `run:` target — an arbitrary Python callable on the leaderboard |

## Lazy imports

Every SDK is imported inside the method that needs it, through `_require`:

```python
def _require(module: str, extra: str):
    try:
        return __import__(module)
    except ImportError as exc:
        raise ConnectorError(
            f"the {extra!r} provider needs the {module!r} package: "
            f"pip install 'agent-arena[{extra}]'"
        ) from exc
```

Two consequences: `pip install agent-arena` pulls in no vendor client, and the
error you get for a missing one names the exact command to fix it. CI installs no
provider SDK on purpose — if the suite ever needs `anthropic` present to pass,
invariant 1 has been broken.

## Provider inference

`registry.infer_provider` resolves a bare model id, so
`models: [claude-opus-5, gpt-4o, gemini-2.5-flash]` works with no `provider:`
field. Resolution order:

1. An explicit `provider:` on the model entry
2. The id's prefix — `claude-*` → anthropic, `gpt-*`/`o3-*` → openai,
   `gemini-*` → gemini, `mock:*` → mock, `ollama/`/`vllm/`/bare `llama`,
   `qwen`, `mistral`… → local
3. A `vendor/model` id → LiteLLM
4. An explicit `api_base` with an unrecognisable id → local, because giving a URL
   is itself the answer: it is an OpenAI-compatible server and the model name can
   be anything

Unresolvable ids raise `ConnectorError` showing the YAML that would fix it.

## The price book

`connectors/pricing.py` plus `model_cards.json`. A card carries input/output
price per million tokens, context window, feature flags and privacy properties.

Three rules govern it:

- **Sourced or absent.** A model whose current list price cannot be sourced is
  left out. `has_pricing` is then false and the model gets no cost metric —
  which, because cost is nulled for the whole run unless every call is priced,
  removes the cost axis for everyone. That is the honest behaviour: a guessed
  price silently corrupts a purchasing decision.
- **`privacy` is deliberately empty for real models.** Whether a DPA is in place
  or zero-data-retention is enabled is a property of *your* contract, not of the
  model. Declare it in your own pricing file.
- **`as_of` is recorded.** Prices move. The catalog states when it was checked.

Override it per project with `pricing.path` (a file) or per model with a `card:`
block. Those beat the shipped catalog, which is how you price a model the arena
does not know or a negotiated rate that differs from list.

## Provider profiles (v2)

`providers:` in `config.yaml` declares named connection profiles, so two API keys
for the same vendor can compete in one run, and a gateway can carry custom
headers, a private CA and a model-prefix rewrite. `ProjectConfig.provider_for()`
resolves a model to its profile.

The config parses and profiles resolve today. **The runner does not yet route
through a profile** — connector wiring is in progress. See
[../guides/api-keys-and-gateways.md](../guides/api-keys-and-gateways.md) and
[../roadmap/status.md](../roadmap/status.md).
