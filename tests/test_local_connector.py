"""The local-model connector, against a real HTTP server.

These tests stand up an actual OpenAI-compatible server on a socket and talk to
it over HTTP — the same path Ollama, LM Studio, llama.cpp and vLLM take. No
mocking of the transport, because the transport is the thing being tested.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

import pytest

from agent_arena.connectors import GenerationRequest
from agent_arena.connectors.local import LocalConnector
from agent_arena.core.errors import ConnectorError

SERVED_MODELS = ["tiny-test-model"]


def make_handler(behaviour: str = "ok"):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:
            pass

        def _send(self, payload, status: int = 200) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.endswith("/models"):
                self._send({"data": [{"id": m} for m in SERVED_MODELS]})
            else:
                self._send({"error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            request = json.loads(self.rfile.read(length) or b"{}")

            if behaviour == "http_error":
                self._send({"error": {"message": "model not loaded"}}, 500)
                return
            if behaviour == "no_choices":
                self._send({"choices": []})
                return
            if behaviour == "no_usage":
                self._send(
                    {
                        "model": request["model"],
                        "choices": [
                            {"message": {"content": "hello"}, "finish_reason": "stop"}
                        ],
                    }
                )
                return

            # Echo enough of the request that tests can assert on what was sent.
            self._send(
                {
                    "model": request["model"],
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": json.dumps(request)},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7},
                }
            )

    return Handler


@pytest.fixture()
def server() -> Iterator[str]:
    yield from _serve("ok")


def _serve(behaviour: str) -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(behaviour))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/v1"
    finally:
        httpd.shutdown()
        httpd.server_close()


def request(prompt: str = "hello", **kwargs) -> GenerationRequest:
    return GenerationRequest(messages=[{"role": "user", "content": prompt}], **kwargs)


# ---- happy path ------------------------------------------------------------


def test_round_trips_over_real_http(server: str) -> None:
    connector = LocalConnector("tiny-test-model", api_base=server)
    result = connector.generate(request("what is 2+2?"))

    sent = json.loads(result.text)
    assert sent["model"] == "tiny-test-model"
    assert sent["messages"] == [{"role": "user", "content": "what is 2+2?"}]
    assert sent["stream"] is False
    assert result.provider == "local"
    assert result.latency_ms > 0


def test_system_prompt_is_sent_as_a_system_message(server: str) -> None:
    connector = LocalConnector("tiny-test-model", api_base=server)
    result = connector.generate(request("q", system="be terse"))

    assert json.loads(result.text)["messages"][0] == {
        "role": "system",
        "content": "be terse",
    }


def test_generation_settings_are_forwarded(server: str) -> None:
    connector = LocalConnector("tiny-test-model", api_base=server)
    result = connector.generate(request("q", max_tokens=64, temperature=0.2))
    sent = json.loads(result.text)

    assert sent["max_tokens"] == 64
    assert sent["temperature"] == 0.2


def test_usage_is_read_from_the_response(server: str) -> None:
    connector = LocalConnector("tiny-test-model", api_base=server)
    result = connector.generate(request())

    assert result.input_tokens == 11
    assert result.output_tokens == 7


def test_missing_usage_falls_back_to_an_estimate() -> None:
    for base in _serve("no_usage"):
        connector = LocalConnector("tiny-test-model", api_base=base)
        result = connector.generate(request("a reasonably long prompt here"))

        # Estimated rather than silently zero, so cost and token metrics stay real.
        assert result.input_tokens > 0
        assert result.output_tokens > 0


# ---- endpoint handling -----------------------------------------------------


def test_defaults_to_ollama() -> None:
    assert LocalConnector("llama3.2").endpoint == "http://localhost:11434/v1/chat/completions"


@pytest.mark.parametrize(
    "api_base",
    ["http://host:1234", "http://host:1234/", "http://host:1234/v1", "http://host:1234/v1/"],
)
def test_api_base_is_normalised(api_base: str) -> None:
    connector = LocalConnector("m", api_base=api_base)
    assert connector.endpoint == "http://host:1234/v1/chat/completions"


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("ollama/llama3.2", "llama3.2"),
        ("local/my-finetune", "my-finetune"),
        ("lmstudio/qwen2.5", "qwen2.5"),
        ("llama3.2", "llama3.2"),
    ],
)
def test_vendor_prefix_is_stripped_from_the_model_name(given: str, expected: str) -> None:
    assert LocalConnector(given).model == expected


# ---- failure modes ---------------------------------------------------------


def test_connection_refused_explains_how_to_fix_it() -> None:
    connector = LocalConnector("llama3.2", api_base="http://127.0.0.1:9")
    with pytest.raises(ConnectorError, match="ollama serve"):
        connector.generate(request())


def test_http_error_surfaces_the_server_message() -> None:
    for base in _serve("http_error"):
        connector = LocalConnector("tiny-test-model", api_base=base)
        with pytest.raises(ConnectorError, match="HTTP 500"):
            connector.generate(request())


def test_empty_choices_is_an_error_not_an_empty_answer() -> None:
    for base in _serve("no_choices"):
        connector = LocalConnector("tiny-test-model", api_base=base)
        with pytest.raises(ConnectorError, match="no choices"):
            connector.generate(request())


# ---- healthcheck -----------------------------------------------------------


def test_healthcheck_passes_for_a_served_model(server: str) -> None:
    assert LocalConnector("tiny-test-model", api_base=server).healthcheck() is None


def test_healthcheck_names_the_missing_model(server: str) -> None:
    reason = LocalConnector("not-pulled", api_base=server).healthcheck()

    assert "not served" in reason
    assert "ollama pull not-pulled" in reason


def test_healthcheck_reports_a_dead_server() -> None:
    reason = LocalConnector("llama3.2", api_base="http://127.0.0.1:9").healthcheck()

    assert "cannot reach" in reason
    assert "ollama serve" in reason
