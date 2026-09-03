"""The uniform model interface.

Every provider — Anthropic, OpenAI, Gemini, LiteLLM, or the offline mock —
looks the same to the runner: hand it a :class:`GenerationRequest`, get a
:class:`GenerationResult` back. Adding a provider means implementing one
method.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GenerationRequest:
    """One call to a model."""

    messages: list[dict[str, Any]]
    system: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    params: dict[str, Any] = field(default_factory=dict)
    """Provider-specific extras, passed through verbatim."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Bookkeeping (test id, trial number, reference). Never sent to real providers."""

    @property
    def prompt(self) -> str:
        """The message list flattened to text — for providers/scorers that want one string."""
        parts = []
        for message in self.messages:
            content = message.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    str(block.get("text", "")) for block in content if isinstance(block, dict)
                )
            parts.append(str(content))
        return "\n\n".join(parts)


@dataclass
class GenerationResult:
    """What a model produced, plus what it cost to produce."""

    text: str
    model: str = ""
    provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: float = 0.0
    finish_reason: str | None = None
    raw: Any = None

    cost_usd: float | None = None
    """What this call actually cost, when the connector knows better than the
    price book. A pipeline target knows its own end-to-end spend across every
    internal call; the catalog cannot. ``None`` falls back to the price book."""

    metrics: dict[str, float] = field(default_factory=dict)
    """Extra numbers the connector measured, weightable in config by name."""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "model": self.model,
            "provider": self.provider,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "latency_ms": self.latency_ms,
            "finish_reason": self.finish_reason,
            "cost_usd": self.cost_usd,
            "metrics": dict(self.metrics),
        }


class Connector(ABC):
    """Base class for model providers."""

    provider: str = "abstract"

    #: Per-request deadline, set by the runner from ``run.timeout_s``. Each
    #: connector forwards it to its SDK; providers that cannot express one
    #: ignore it rather than pretending to enforce it.
    timeout_s: float | None = None

    #: Extra HTTP headers a provider profile asked for — a gateway's routing
    #: config, an organisation id. Empty for a plain vendor call.
    headers: dict[str, str]

    #: ``True`` to verify certificates normally, a path to use as a CA bundle,
    #: or ``False`` to skip verification entirely. The last is occasionally
    #: necessary against an internal endpoint and is never a good idea; the
    #: caller is warned rather than silently protected.
    verify_tls: bool | str = True

    #: Proxy URL, when a profile routes through one.
    proxy: str | None = None

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        api_base: str | None = None,
        headers: dict[str, str] | None = None,
        verify_tls: bool | str = True,
        proxy: str | None = None,
        **params: Any,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.api_base = api_base
        self.headers = dict(headers or {})
        self.verify_tls = verify_tls
        self.proxy = proxy
        self.params = params

    @abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Produce a completion. Raise on failure — the runner handles retries."""

    def close(self) -> None:
        """Release any client resources. Overridden where it matters."""

    def healthcheck(self) -> str | None:
        """Return a reason this model is unreachable, or ``None`` if it is fine.

        Checked before a run so an unreachable endpoint is *skipped with an
        explanation* rather than producing one failed call per test case.
        Only implemented where the check is instant and meaningful — a local
        server either accepts a socket or does not.
        """
        return None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} model={self.model!r}>"


def estimate_tokens(text: str) -> int:
    """Rough token count for providers that report no usage.

    Deliberately crude (~4 chars/token). Only used to keep cost and token
    metrics non-zero when a provider gives us nothing; results derived from it
    are flagged ``estimated`` in the store.
    """
    if not text:
        return 0
    return max(1, len(str(text)) // 4)
