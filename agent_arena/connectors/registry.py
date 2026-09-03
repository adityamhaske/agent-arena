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
from .callable_target import CallableConnector
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
    "openai_compatible": LocalConnector,
    "vllm": LocalConnector,
    "llamacpp": LocalConnector,
    "mock": MockConnector,
    "callable": CallableConnector,
    "pipeline": CallableConnector,
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


def build_connector(
    spec: Any,
    defaults: dict[str, Any] | None = None,
    profile: Any = None,
) -> Connector:
    """Instantiate the connector for one :class:`~agent_arena.core.config.ModelSpec`.

    ``profile`` is the :class:`~agent_arena.core.config.ProviderSpec` the model
    selected, when it selected one. It supplies the endpoint, the credential,
    any extra headers, the TLS and proxy settings, and a model-id rewrite —
    which together are what make two accounts on the same vendor, or a
    corporate gateway, expressible at all.
    """
    provider = resolve_provider(spec, profile=profile, strict=True)
    factory = CONNECTORS.get(provider)
    if factory is None:
        raise ConnectorError(
            f"unknown provider {provider!r} for model {spec.model!r}. "
            f"Known providers: {', '.join(sorted(CONNECTORS))}"
        )

    api_key = None
    if profile is not None and getattr(profile, "api_key_ref", None):
        # A reference, never a literal — resolved here so no caller has to hold
        # the raw value. Secret.reveal() is the only way to the string, and the
        # SDK call below is the only place that happens.
        from ..core.secrets import resolve as _resolve_secret  # noqa: PLC0415

        secret = _resolve_secret(profile.api_key_ref, base_dir=getattr(spec, "base_dir", None))
        if secret is None:
            raise ConnectorError(
                f"provider {profile.id!r} declares api_key={profile.api_key_ref!r} "
                "but it resolves to nothing. Check the variable, file or keyring entry."
            )
        api_key = secret.reveal()
    elif spec.api_key_env:
        api_key = os.environ.get(spec.api_key_env)
        if not api_key:
            raise ConnectorError(
                f"model {spec.key!r} declares api_key_env={spec.api_key_env!r} "
                "but that variable is not set"
            )
    elif provider in _API_KEY_ENVS:
        api_key = os.environ.get(_API_KEY_ENVS[provider])

    model_id = spec.model
    api_base = spec.api_base
    transport: dict[str, Any] = {}
    if profile is not None:
        # The model entry still wins where it is explicit: a profile is a
        # default for the connection, not an override of a deliberate choice.
        api_base = api_base or getattr(profile, "base_url", None)
        prefix = getattr(profile, "model_prefix", None)
        if prefix and not model_id.startswith(prefix):
            model_id = f"{prefix}{model_id}"
        transport = {
            "headers": dict(getattr(profile, "headers", {}) or {}),
            "verify_tls": getattr(profile, "verify_tls", True),
            "proxy": getattr(profile, "proxy", None),
        }

    profile_params = (getattr(profile, "params", None) or {}) if profile is not None else {}
    params = {**(defaults or {}).get("params", {}), **profile_params, **spec.params}
    if provider == "callable":
        params["run"] = spec.run or spec.model
        params["base_dir"] = getattr(spec, "base_dir", None)
    # Generation-level settings live on the request, not the client.
    for reserved in ("temperature", "max_tokens", "system"):
        params.pop(reserved, None)

    try:
        connector = factory(
            model=model_id,
            api_key=api_key,
            api_base=api_base,
            **transport,
            **params,
        )
        if profile is not None and getattr(profile, "timeout_s", None):
            connector.timeout_s = profile.timeout_s
        return connector
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
_PROVIDER_ALIASES = {
    "ollama": "local", "lmstudio": "local", "google": "gemini", "pipeline": "callable",
    # Any OpenAI-shaped endpoint — a gateway, a self-hosted server — is served
    # by the stdlib HTTP connector, which is the one that honours headers, a
    # custom CA and a proxy.
    "openai_compatible": "local", "vllm": "local", "llamacpp": "local",
}


def canonical_provider(provider: str | None) -> str | None:
    return _PROVIDER_ALIASES.get(provider, provider) if provider else provider


def resolve_provider(spec: Any, profile: Any = None, strict: bool = False) -> str | None:
    """The provider a model spec will use, without constructing a connector.

    Returns ``None`` rather than raising when the id is unrecognisable (unless
    ``strict``), so reporting paths can describe a model they could not route.
    """
    if getattr(spec, "run", None):
        # A target names the callable to execute; nothing about the id can
        # override that.
        return "callable"
    if profile is not None:
        # A declared profile names its own kind; the model's `provider:` field
        # was the reference that selected it, not a vendor name.
        return canonical_provider(getattr(profile, "kind", None) or spec.provider)
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
    # Local and mock models run without credentials by definition; a callable
    # target handles its own, inside the pipeline we are calling.
    if provider in (None, "mock", "local", "ollama", "lmstudio", "callable"):
        return None
    if spec.api_key_env:
        return spec.api_key_env
    return _API_KEY_ENVS.get(provider)
