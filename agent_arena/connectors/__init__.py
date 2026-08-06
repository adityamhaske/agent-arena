"""Model providers behind one interface, plus the pricing/capability catalog."""

from .base import Connector, GenerationRequest, GenerationResult, estimate_tokens
from .local import LocalConnector
from .mock import MockConnector
from .pricing import ModelCard, PriceBook, build_price_book
from .providers import (
    AnthropicConnector,
    GeminiConnector,
    LiteLLMConnector,
    OpenAIConnector,
)
from .registry import (
    CONNECTORS,
    build_connector,
    infer_provider,
    register_connector,
    requires_api_key,
    resolve_provider,
)

__all__ = [
    "CONNECTORS",
    "AnthropicConnector",
    "Connector",
    "GeminiConnector",
    "GenerationRequest",
    "GenerationResult",
    "LiteLLMConnector",
    "LocalConnector",
    "MockConnector",
    "ModelCard",
    "OpenAIConnector",
    "PriceBook",
    "build_connector",
    "build_price_book",
    "estimate_tokens",
    "infer_provider",
    "register_connector",
    "resolve_provider",
    "requires_api_key",
]
