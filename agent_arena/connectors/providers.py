"""Real model providers.

Every SDK is imported lazily inside ``generate``/``__init__`` so the arena
installs and runs — including its whole test suite, against the mock — with no
provider SDK present. Install only what you actually evaluate::

    pip install agent-arena[anthropic]     # or [openai], [gemini], [litellm], [all]
"""

from __future__ import annotations

import os
import time
from typing import Any

from ..core.errors import ConnectorError
from .base import Connector, GenerationRequest, GenerationResult, estimate_tokens

DEFAULT_MAX_TOKENS = 1024

#: Anthropic models that reject `temperature`/`top_p`/`top_k` with a 400.
#: Sending them anyway turns a working config into a hard failure, so the
#: connector drops them for these families instead of forwarding blindly.
_NO_SAMPLING_PARAMS = (
    "claude-fable-",
    "claude-mythos-",
    "claude-opus-5",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-sonnet-5",
)

#: Above this, a non-streaming request risks an SDK HTTP timeout.
_STREAM_ABOVE_MAX_TOKENS = 16000


def _require(module: str, extra: str):
    """Import a provider SDK, or explain exactly how to install it."""
    try:
        return __import__(module)
    except ImportError as exc:
        raise ConnectorError(
            f"the {extra!r} provider needs the {module!r} package: "
            f"pip install 'agent-arena[{extra}]'"
        ) from exc


class AnthropicConnector(Connector):
    """Claude models via the official Anthropic SDK."""

    provider = "anthropic"
    default_api_key_env = "ANTHROPIC_API_KEY"

    def __init__(self, model: str, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(model, api_key=api_key, **kwargs)
        self._client = None

    @property
    def client(self):
        if self._client is None:
            anthropic = _require("anthropic", "anthropic")
            options: dict[str, Any] = {}
            # An unset ANTHROPIC_API_KEY does not mean there are no credentials:
            # the SDK also resolves auth tokens and `ant auth login` profiles.
            if self.api_key:
                options["api_key"] = self.api_key
            if self.api_base:
                options["base_url"] = self.api_base
            self._client = anthropic.Anthropic(**options)
        return self._client

    def _supports_sampling_params(self) -> bool:
        return not any(self.model.startswith(prefix) for prefix in _NO_SAMPLING_PARAMS)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        max_tokens = request.max_tokens or DEFAULT_MAX_TOKENS
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": _plain_messages(request.messages),
        }
        if request.system:
            payload["system"] = request.system
        if request.temperature is not None and self._supports_sampling_params():
            payload["temperature"] = request.temperature

        extra = {**self.params, **request.params}
        extra.pop("mode", None)
        for key, value in extra.items():
            if key in ("effort", "task_budget"):
                payload.setdefault("output_config", {})[key] = value
            else:
                payload[key] = value

        client = self.client
        if self.timeout_s:
            client = client.with_options(timeout=self.timeout_s)

        started = time.perf_counter()
        # Above ~16K output tokens a non-streaming request risks an HTTP timeout.
        if max_tokens > _STREAM_ABOVE_MAX_TOKENS:
            with client.messages.stream(**payload) as stream:
                response = stream.get_final_message()
        else:
            response = client.messages.create(**payload)
        latency_ms = (time.perf_counter() - started) * 1000.0

        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        usage = getattr(response, "usage", None)
        return GenerationResult(
            text=text,
            model=getattr(response, "model", self.model),
            provider=self.provider,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            latency_ms=latency_ms,
            finish_reason=getattr(response, "stop_reason", None),
            raw=None,
        )


class OpenAIConnector(Connector):
    """GPT-family models via the official OpenAI SDK."""

    provider = "openai"
    default_api_key_env = "OPENAI_API_KEY"

    def __init__(self, model: str, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(model, api_key=api_key, **kwargs)
        self._client = None

    @property
    def client(self):
        if self._client is None:
            _require("openai", "openai")
            from openai import OpenAI  # noqa: PLC0415

            options: dict[str, Any] = {}
            if self.api_key:
                options["api_key"] = self.api_key
            if self.api_base:
                options["base_url"] = self.api_base
            self._client = OpenAI(**options)
        return self._client

    def generate(self, request: GenerationRequest) -> GenerationResult:
        messages = _plain_messages(request.messages)
        if request.system:
            messages = [{"role": "system", "content": request.system}, *messages]

        extra = {**self.params, **request.params}
        extra.pop("mode", None)
        token_param = str(extra.pop("token_param", "max_completion_tokens"))

        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if request.max_tokens:
            payload[token_param] = request.max_tokens
        # Popped unconditionally: `and` short-circuits when temperature is
        # None, which used to leave this control flag in the payload and
        # send it to the provider as an unknown parameter.
        send_temperature = extra.pop("send_temperature", True)
        if request.temperature is not None and send_temperature:
            payload["temperature"] = request.temperature
        if self.timeout_s:
            payload.setdefault("timeout", self.timeout_s)
        payload.update(extra)

        started = time.perf_counter()
        response = self.client.chat.completions.create(**payload)
        latency_ms = (time.perf_counter() - started) * 1000.0

        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        return GenerationResult(
            text=choice.message.content or "",
            model=getattr(response, "model", self.model),
            provider=self.provider,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            latency_ms=latency_ms,
            finish_reason=getattr(choice, "finish_reason", None),
        )


class GeminiConnector(Connector):
    """Gemini models via google-generativeai."""

    provider = "gemini"
    default_api_key_env = "GEMINI_API_KEY"

    def generate(self, request: GenerationRequest) -> GenerationResult:
        _require("google.generativeai", "gemini")
        import google.generativeai as genai  # noqa: PLC0415

        api_key = self.api_key or os.environ.get(self.default_api_key_env)
        if api_key:
            genai.configure(api_key=api_key)

        generation_config: dict[str, Any] = {}
        if request.max_tokens:
            generation_config["max_output_tokens"] = request.max_tokens
        if request.temperature is not None:
            generation_config["temperature"] = request.temperature
        extra = {**self.params, **request.params}
        extra.pop("mode", None)
        generation_config.update(extra)

        model = genai.GenerativeModel(
            model_name=self.model,
            system_instruction=request.system or None,
        )
        contents = [
            {"role": "model" if m.get("role") == "assistant" else "user",
             "parts": [str(m.get("content", ""))]}
            for m in request.messages
        ]

        started = time.perf_counter()
        response = model.generate_content(contents, generation_config=generation_config or None)
        latency_ms = (time.perf_counter() - started) * 1000.0

        text = "".join(part.text for part in response.parts if getattr(part, "text", None))
        usage = getattr(response, "usage_metadata", None)
        return GenerationResult(
            text=text,
            model=self.model,
            provider=self.provider,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            latency_ms=latency_ms,
            finish_reason="stop",
        )


class LiteLLMConnector(Connector):
    """Anything LiteLLM can reach, behind the same interface.

    Use this to evaluate a provider the arena has no native connector for:
    set ``provider: litellm`` and give the model id LiteLLM expects
    (``bedrock/...``, ``together_ai/...``, ``ollama/...``).
    """

    provider = "litellm"

    def generate(self, request: GenerationRequest) -> GenerationResult:
        litellm = _require("litellm", "litellm")

        messages = _plain_messages(request.messages)
        if request.system:
            messages = [{"role": "system", "content": request.system}, *messages]

        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if self.api_key:
            payload["api_key"] = self.api_key
        if self.api_base:
            payload["api_base"] = self.api_base
        if self.timeout_s:
            payload["timeout"] = self.timeout_s
        extra = {**self.params, **request.params}
        extra.pop("mode", None)
        payload.update(extra)

        started = time.perf_counter()
        response = litellm.completion(**payload)
        latency_ms = (time.perf_counter() - started) * 1000.0

        choice = response.choices[0]
        content = getattr(choice.message, "content", "") or ""
        usage = getattr(response, "usage", None)
        return GenerationResult(
            text=content,
            model=getattr(response, "model", self.model),
            provider=self.provider,
            input_tokens=getattr(usage, "prompt_tokens", 0) or estimate_tokens(request.prompt),
            output_tokens=getattr(usage, "completion_tokens", 0) or estimate_tokens(content),
            latency_ms=latency_ms,
            finish_reason=getattr(choice, "finish_reason", None),
        )


def _plain_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise to ``[{"role": ..., "content": ...}]`` with string content."""
    normalized = []
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                str(block.get("text", "")) for block in content if isinstance(block, dict)
            )
        normalized.append({"role": message.get("role", "user"), "content": str(content)})
    return normalized
