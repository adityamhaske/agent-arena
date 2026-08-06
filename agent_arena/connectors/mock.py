"""A deterministic, offline model.

The mock exists so the arena is testable and demonstrable with no API keys, no
network, and no spend — and so a project can pin a synthetic baseline into its
model list to sanity-check its own scorers and weights before paying for a real
sweep.

Configure it through the model's ``params``::

    models:
      - key: perfect
        model: mock:oracle           # always returns the reference
      - key: coin_flip
        model: mock:flaky
        params: {accuracy: 60, latency_ms: 250}
      - key: stubborn
        model: mock:fixed
        params: {text: "refund"}

Modes: ``oracle`` (returns the reference), ``flaky`` (returns the reference
``accuracy`` percent of the time, deterministically per test), ``fixed``
(always ``params.text``), ``echo`` (returns the prompt), ``empty``.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from ..core.errors import ConnectorError
from .base import Connector, GenerationRequest, GenerationResult, estimate_tokens

MODES = ("oracle", "flaky", "fixed", "echo", "empty")


class MockConnector(Connector):
    """Deterministic offline stand-in for a real model."""

    provider = "mock"

    def __init__(self, model: str = "mock:oracle", **kwargs: Any) -> None:
        super().__init__(model, **kwargs)
        _, _, suffix = model.partition(":")
        self.mode = str(self.params.get("mode") or suffix or "oracle").lower()
        if self.mode not in MODES:
            raise ConnectorError(
                f"unknown mock mode {self.mode!r}; expected one of {', '.join(MODES)}"
            )
        self.accuracy = float(self.params.get("accuracy", 100.0))
        self.latency_ms = float(self.params.get("latency_ms", 0.0))
        self.wrong_text = str(self.params.get("wrong_text", "I am not sure."))
        self.sleep = bool(self.params.get("sleep", False))

    def generate(self, request: GenerationRequest) -> GenerationResult:
        started = time.perf_counter()
        if self.sleep and self.latency_ms:
            time.sleep(self.latency_ms / 1000.0)

        text = self._respond(request)

        measured = (time.perf_counter() - started) * 1000.0
        latency = self.latency_ms if (self.latency_ms and not self.sleep) else measured

        return GenerationResult(
            text=text,
            model=self.model,
            provider=self.provider,
            input_tokens=estimate_tokens(request.prompt) + estimate_tokens(request.system or ""),
            output_tokens=estimate_tokens(text),
            latency_ms=latency,
            finish_reason="stop",
            raw={"mock_mode": self.mode},
        )

    # ---- behaviour ----------------------------------------------------

    def _respond(self, request: GenerationRequest) -> str:
        reference = request.metadata.get("reference")

        if self.mode == "empty":
            return ""
        if self.mode == "echo":
            return request.prompt
        if self.mode == "fixed":
            return str(self.params.get("text", ""))
        if self.mode == "oracle":
            return _stringify(reference)
        # flaky
        if self._draw(request) < self.accuracy:
            return _stringify(reference)
        return self.wrong_text

    def _draw(self, request: GenerationRequest) -> float:
        """A stable pseudo-random number in [0, 100) for this (model, test, trial)."""
        seed = "|".join(
            str(x)
            for x in (
                self.model,
                self.params.get("seed", ""),
                request.metadata.get("test_id", request.prompt[:64]),
                request.metadata.get("trial", 1),
            )
        )
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % 10000 / 100.0


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        # A list reference means "any of these is acceptable" — answer with the
        # first, the way a real model would give one answer rather than a set.
        return _stringify(value[0]) if value else ""
    if isinstance(value, dict):
        return json.dumps(value)
    return str(value)
