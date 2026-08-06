#!/usr/bin/env python3
"""A stand-in local model server, for reproducing the demo without Ollama.

This is **not** a language model. It is ~100 lines of stdlib HTTP that speaks
the same ``POST /v1/chat/completions`` protocol Ollama, LM Studio, llama.cpp
and vLLM all expose, so the arena's local code path can be exercised
end-to-end on a machine with no model installed.

It serves three "models" with deliberately different quality/speed profiles,
answering deterministically per prompt so the demo reproduces exactly:

    python demo/fake_local_server.py --port 11434

Then point a project at ``http://localhost:11434/v1``. To run the same demo
against a *real* local model instead, skip this script and start Ollama —
nothing else changes but the model names.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Each entry: how often it answers correctly, and how slow it is.
MODELS: dict[str, dict[str, float]] = {
    "demo-large": {"accuracy": 0.95, "latency_ms": 900.0},
    "demo-medium": {"accuracy": 0.80, "latency_ms": 320.0},
    "demo-small": {"accuracy": 0.60, "latency_ms": 90.0},
}

QUEUES = ("billing", "technical", "account", "shipping", "refund", "spam")

# The "knowledge" this fake model has: keyword → queue. Real models get this
# from training; here it is a lookup, which is why the interesting variable is
# how often each profile is allowed to use it.
KEYWORDS: tuple[tuple[str, str], ...] = (
    (r"charg|invoic|billed|bill\b|payment|card", "billing"),
    (r"crash|error|500|endpoint|api|sso|login loop|bug|broken", "technical"),
    (r"password|account|seat|owner|workspace|sign in|access", "account"),
    (r"deliver|track|parcel|shipment|address|order #", "shipping"),
    (r"refund|money back|return|cancel.*plan", "refund"),
    (r"congratulations|winner|click here|btc|crypto|prize", "spam"),
)


def classify(prompt: str) -> str:
    lowered = prompt.lower()
    for pattern, queue in KEYWORDS:
        if re.search(pattern, lowered):
            return queue
    return "technical"


def answer(model: str, prompt: str) -> str:
    """Deterministic per (model, prompt): the same question always gets the
    same answer, so a demo run reproduces exactly."""
    profile = MODELS[model]
    seed = f"{model}|{prompt}".encode("utf-8")
    draw = int(hashlib.sha256(seed).hexdigest()[:8], 16) % 10000 / 10000.0

    correct = classify(prompt)
    if draw < profile["accuracy"]:
        return correct
    # A wrong-but-plausible answer, the way a smaller model actually fails.
    wrong = [q for q in QUEUES if q != correct]
    return wrong[int(hashlib.sha256(seed).hexdigest()[8:12], 16) % len(wrong)]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:  # noqa: D102 - silence per-request logging
        pass

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.rstrip("/").endswith("/models"):
            self._send(
                {"object": "list", "data": [{"id": name, "object": "model"} for name in MODELS]}
            )
        else:
            self._send({"error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send({"error": "not found"}, status=404)
            return

        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length) or b"{}")

        model = request.get("model", "demo-medium")
        if model not in MODELS:
            self._send({"error": {"message": f"model '{model}' not found"}}, status=404)
            return

        prompt = " ".join(
            str(m.get("content", ""))
            for m in request.get("messages", [])
            if m.get("role") != "system"
        )
        time.sleep(MODELS[model]["latency_ms"] / 1000.0)
        text = answer(model, prompt)

        self._send(
            {
                "id": "chatcmpl-demo",
                "object": "chat.completion",
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": max(1, len(prompt) // 4),
                    "completion_tokens": max(1, len(text) // 4),
                    "total_tokens": max(2, (len(prompt) + len(text)) // 4),
                },
            }
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=11434)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"stand-in local model server on http://{args.host}:{args.port}/v1")
    print(f"serving: {', '.join(MODELS)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
