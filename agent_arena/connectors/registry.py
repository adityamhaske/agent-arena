"""Turning a config entry into a live connector.

Resolution order:

1. an explicit ``provider:`` on the model entry
2. the model id's prefix (``claude-*`` → anthropic, ``gpt-*``/``o3-*`` → openai,
   ``gemini-*`` → gemini, ``mock:*`` → mock)
3. a ``vendor/model`` id → LiteLLM

so ``models: [claude-opus-5, gpt-4o, gemini-2.5-flash]`` just works, and
anything exotic can be routed with one explicit line.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from ..core.errors import ConnectorError
from .base import Connector
from .local import LocalConnector
from .mock import MockConnector
from .providers import (
    AnthropicConnector,
    GeminiConnector,
    LiteLLMConnector,
    OpenAIConnector,
)

CONNECTORS: dict[str, type[Connector]] = {
    "anthropic": AnthropicConnector,
    "openai": OpenAIConnector,
    "gemini": GeminiConnector,
    "google": GeminiConnector,
    "litellm": LiteLLMConnector,
    "local": LocalConnector,
    "ollama": LocalConnector,
    "lmstudio": LocalConnector,
    "mock": MockConnector,
}

_PREFIX_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("claude-", "claude.", "anthropic."), "anthropic"),
    (("gpt-", "gpt.", "o1-", "o3-", "o4-", "chatgpt", "text-davinci"), "openai"),
    (("gemini-", "models/gemini"), "gemini"),
    (("mock:", "mock-"), "mock"),
    # Local runtimes: routed to the stdlib HTTP connector, so evaluating a
    # model on your own machine needs no SDK installed at all.
    (("ollama/", "local/", "lmstudio/", "llamacpp/", "vllm/"), "local"),
    (("llama", "qwen", "mistral", "mixtral", "phi", "gemma", "deepseek", "codellama"), "local"),
)

_API_KEY_ENVS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "google": "GEMINI_API_KEY",
}


def infer_provider(model: str) -> str:
    """Guess the provider from a model id."""
    lowered = model.lower()
    if lowered == "mock":
        return "mock"
    for prefixes, provider in _PREFIX_RULES:
        if lowered.startswith(prefixes):
            return provider
    if "/" in model:
        # bedrock/…, together_ai/…, azure/… — LiteLLM's own namespacing.
        return "litellm"
    raise ConnectorError(
        f"cannot infer a provider for model {model!r}. Set it explicitly:\n"
        "  models:\n"
        f"    - model: {model}\n"
        "      provider: litellm     # or anthropic | openai | gemini | mock"
    )


def register_connector(name: str, factory: Callable[..., Connector]) -> None:
    """Add a provider at runtime (for embedding the arena in a larger system)."""
    CONNECTORS[name] = factory  # type: ignore[assignment]


def build_connector(spec: Any, defaults: dict[str, Any] | None = None) -> Connector:
    """Instantiate the connector for one :class:`~agent_arena.core.config.ModelSpec`."""
    provider = resolve_provider(spec, strict=True)
    factory = CONNECTORS.get(provider)
    if factory is None:
        raise ConnectorError(
            f"unknown provider {provider!r} for model {spec.model!r}. "
            f"Known providers: {', '.join(sorted(CONNECTORS))}"
        )

    api_key = None
    if spec.api_key_env:
        api_key = os.environ.get(spec.api_key_env)
        if not api_key:
            raise ConnectorError(
                f"model {spec.key!r} declares api_key_env={spec.api_key_env!r} "
                "but that variable is not set"
            )
    elif provider in _API_KEY_ENVS:
        api_key = os.environ.get(_API_KEY_ENVS[provider])

    params = {**(defaults or {}).get("params", {}), **spec.params}
    # Generation-level settings live on the request, not the client.
    for reserved in ("temperature", "max_tokens", "system"):
        params.pop(reserved, None)

    try:
        return factory(
            model=spec.model,
            api_key=api_key,
            api_base=spec.api_base,
            **params,
        )
    except ConnectorError:
        raise
    except TypeError as exc:
        raise ConnectorError(
            f"could not construct the {provider} connector for {spec.model!r} "
            f"with params {params!r}: {exc}"
        ) from exc


#: Several spellings route to the same connector. Canonicalising here keeps
#: the model-card lookup, the cost calculation and the report in agreement —
#: `provider: ollama` must find the same `local` card as a bare `llama3.2`.
_PROVIDER_ALIASES = {"ollama": "local", "lmstudio": "local", "google": "gemini"}


def canonical_provider(provider: str | None) -> str | None:
    return _PROVIDER_ALIASES.get(provider, provider) if provider else provider


def resolve_provider(spec: Any, strict: bool = False) -> str | None:
    """The provider a model spec will use, without constructing a connector.

    Returns ``None`` rather than raising when the id is unrecognisable (unless
    ``strict``), so reporting paths can describe a model they could not route.
    """
    if getattr(spec, "provider", None):
        return canonical_provider(spec.provider)
    try:
        return canonical_provider(infer_provider(spec.model))
    except ConnectorError:
        # An explicit endpoint is itself the answer: you gave us a URL, so this
        # is an OpenAI-compatible server and the model name can be anything.
        if getattr(spec, "api_base", None):
            return "local"
        if strict:
            raise
        return None


def requires_api_key(spec: Any) -> str | None:
    """The env var this model needs, or ``None`` when it needs no credentials."""
    provider = resolve_provider(spec)
    # Local and mock models run without credentials by definition.
    if provider in (None, "mock", "local", "ollama", "lmstudio"):
        return None
    if spec.api_key_env:
        return spec.api_key_env
    return _API_KEY_ENVS.get(provider)
