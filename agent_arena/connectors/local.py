"""Local models — Ollama, LM Studio, llama.cpp, vLLM, anything OpenAI-compatible.

Deliberately built on ``urllib`` from the standard library rather than an SDK.
Evaluating a model running on your own laptop should not require installing a
vendor client, and a local endpoint is a plain HTTP POST:

.. code-block:: yaml

    models:
      - key: llama32
        model: llama3.2                     # provider inferred: ollama
      - key: qwen
        model: ollama/qwen2.5-coder:7b      # explicit vendor prefix also works
      - key: lmstudio
        model: local/my-model
        api_base: http://localhost:1234/v1

Defaults to Ollama's ``http://localhost:11434/v1``. Point ``api_base`` at any
server speaking ``POST /v1/chat/completions``.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from ..core.errors import ConnectorError
from .base import Connector, GenerationRequest, GenerationResult, estimate_tokens

DEFAULT_API_BASE = "http://localhost:11434/v1"

#: Model-name prefixes that mean "strip this, it is routing, not the model".
_VENDOR_PREFIXES = ("ollama/", "local/", "lmstudio/", "llamacpp/", "vllm/")


class LocalConnector(Connector):
    """Any OpenAI-compatible endpoint on your own machine."""

    provider = "local"

    def __init__(self, model: str, **kwargs: Any) -> None:
        super().__init__(model, **kwargs)
        for prefix in _VENDOR_PREFIXES:
            if self.model.startswith(prefix):
                self.model = self.model[len(prefix) :]
                break
        self.api_base = (self.api_base or DEFAULT_API_BASE).rstrip("/")

    @property
    def endpoint(self) -> str:
        base = self.api_base
        # Accept both ".../v1" and a bare host, and a full path if given.
        if base.endswith("/chat/completions"):
            return base
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        return f"{base}/chat/completions"

    def _opener(self) -> Any:
        """A urllib opener honouring the profile's TLS and proxy settings.

        Built per call rather than cached: a connector is shared across worker
        threads, and an opener is not documented as thread-safe to construct.
        """
        handlers: list[Any] = []
        if self.proxy:
            handlers.append(urllib.request.ProxyHandler({"http": self.proxy, "https": self.proxy}))
        context = self._ssl_context()
        if context is not None:
            handlers.append(urllib.request.HTTPSHandler(context=context))
        # Always a real opener: the urllib.request module exposes urlopen, not
        # open, so returning the module would break every caller.
        return urllib.request.build_opener(*handlers)

    def _ssl_context(self):
        if self.verify_tls is True:
            return None
        import ssl  # noqa: PLC0415 — only needed for a non-default TLS setup

        if self.verify_tls is False:
            # Deliberately loud: anything on the path can now read the prompts
            # and the API key. A profile has to ask for this explicitly.
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            return context
        return ssl.create_default_context(cafile=str(self.verify_tls))

    def healthcheck(self) -> str | None:
        """Confirm something is listening and knows about this model."""
        models_url = self.endpoint.replace("/chat/completions", "/models")
        try:
            with self._opener().open(models_url, timeout=5.0) as response:
                catalog = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError:
            # Something is listening but has no /v1/models route (llama.cpp
            # and some vLLM builds). Not fatal — the completion call is the
            # real test. Must precede URLError, which HTTPError subclasses.
            return None
        except urllib.error.URLError as exc:
            return (
                f"cannot reach {self.api_base} ({exc.reason}) — "
                "start it with `ollama serve`"
            )
        except (json.JSONDecodeError, OSError):
            # Something is listening but does not speak the models endpoint.
            # Not fatal: the completion call is the real test.
            return None

        served = {
            str(entry.get("id", "")) for entry in (catalog.get("data") or []) if isinstance(entry, dict)
        }
        if served and not any(
            name == self.model or name.startswith(f"{self.model}:") for name in served
        ):
            available = ", ".join(sorted(served)[:6]) or "none"
            return (
                f"model {self.model!r} is not served by {self.api_base} "
                f"(available: {available}) — try `ollama pull {self.model}`"
            )
        return None

    def generate(self, request: GenerationRequest) -> GenerationResult:
        messages = [
            {"role": m.get("role", "user"), "content": _text(m.get("content", ""))}
            for m in request.messages
        ]
        if request.system:
            messages = [{"role": "system", "content": request.system}, *messages]

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens
        if request.temperature is not None:
            payload["temperature"] = request.temperature

        extra = {**self.params, **request.params}
        extra.pop("mode", None)
        payload.update(extra)

        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", **self.headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        http_request = urllib.request.Request(  # noqa: S310 - fixed http(s) endpoint
            self.endpoint, data=body, headers=headers, method="POST"
        )

        started = time.perf_counter()
        try:
            with self._opener().open(
                http_request, timeout=self.timeout_s or 120.0
            ) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise ConnectorError(
                f"{self.endpoint} returned HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ConnectorError(
                f"cannot reach {self.endpoint} ({exc.reason}). "
                "Is the server running? For Ollama: `ollama serve`, then "
                f"`ollama pull {self.model}`."
            ) from exc
        except json.JSONDecodeError as exc:
            raise ConnectorError(
                f"{self.endpoint} did not return JSON — is it an OpenAI-compatible endpoint?"
            ) from exc
        latency_ms = (time.perf_counter() - started) * 1000.0

        choices = data.get("choices") or []
        if not choices:
            raise ConnectorError(f"{self.endpoint} returned no choices: {str(data)[:200]}")
        message = choices[0].get("message") or {}
        text = message.get("content") or ""

        usage = data.get("usage") or {}
        return GenerationResult(
            text=text,
            model=data.get("model", self.model),
            provider=self.provider,
            # Local servers do not always report usage; estimate so the tokens
            # and cost metrics stay populated rather than silently zero.
            input_tokens=usage.get("prompt_tokens") or estimate_tokens(request.prompt),
            output_tokens=usage.get("completion_tokens") or estimate_tokens(text),
            latency_ms=latency_ms,
            finish_reason=choices[0].get("finish_reason"),
        )


def _text(content: Any) -> str:
    if isinstance(content, list):
        return " ".join(
            str(block.get("text", "")) for block in content if isinstance(block, dict)
        )
    return str(content)
