"""What gets retried, and how long we wait before trying again.

These tests exist because all three failures they pin down are invisible in a
green suite and expensive in a real run: retrying a 401 turns a one-second
"your key is wrong" into a slow, confusing one; un-jittered backoff makes every
worker that hit a rate limit come back at the same instant and hit it again;
and ignoring ``Retry-After`` means sleeping a made-up number when the provider
already sent the real one.

The fake exceptions below are deliberately hand-rolled rather than imported
from a provider SDK — classification has to work with no SDK installed at all
(AGENTS.md, invariant 1), and the CI test job installs none.
"""

from __future__ import annotations

import email.message
import random
import socket
import textwrap
import time
import urllib.error
from email.utils import formatdate
from pathlib import Path

import pytest

from agent_arena.connectors.base import GenerationRequest, GenerationResult
from agent_arena.core import runner as runner_module
from agent_arena.core.retry import (
    MAX_SLEEP_S,
    Retryability,
    classify,
    retry_after_seconds,
    sleep_for,
)
from agent_arena.core.runner import ArenaRunner

from .conftest import write_project


class FakeResponse:
    """The `.response` an httpx-backed SDK error carries."""

    def __init__(self, status_code: int | None = None, headers: dict | None = None) -> None:
        self.status_code = status_code
        self.headers = dict(headers or {})


class FakeAPIError(Exception):
    """Shaped like an `openai`/`anthropic` status error: a code and a response."""

    def __init__(
        self, status_code: int | None = None, headers: dict | None = None, message: str = "boom"
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = FakeResponse(status_code, headers)


class NestedStatusError(Exception):
    """Only the response knows the status — no `status_code` on the exception."""

    def __init__(self, status_code: int, headers: dict | None = None) -> None:
        super().__init__("nested")
        self.response = FakeResponse(status_code, headers)


def _named(name: str, base: type[Exception] = Exception) -> Exception:
    """An exception whose only clue is its class name, the way a lazily-imported
    SDK's errors reach us."""
    return type(name, (base,), {})("named error")


class ClassificationTests:
    @pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
    def test_a_client_error_is_terminal(self, status: int) -> None:
        assert classify(FakeAPIError(status)) is Retryability.TERMINAL

    @pytest.mark.parametrize("status", [408, 409, 425, 429, 500, 502, 503, 529])
    def test_a_transient_status_is_retryable(self, status: int) -> None:
        assert classify(FakeAPIError(status)) is Retryability.RETRYABLE

    def test_an_unlisted_client_error_is_still_terminal(self) -> None:
        """The request we would resend is the one that was just rejected."""
        assert classify(FakeAPIError(402)) is Retryability.TERMINAL

    def test_a_status_hidden_on_the_response_is_found(self) -> None:
        assert classify(NestedStatusError(429)) is Retryability.RETRYABLE
        assert classify(NestedStatusError(401)) is Retryability.TERMINAL

    def test_urllib_reports_its_status_as_code(self) -> None:
        headers = email.message.Message()
        rate_limited = urllib.error.HTTPError("http://x", 429, "Too Many", headers, None)
        not_found = urllib.error.HTTPError("http://x", 404, "Nope", headers, None)

        # HTTPError is a URLError, so the status has to win over the base class.
        assert classify(rate_limited) is Retryability.RETRYABLE
        assert classify(not_found) is Retryability.TERMINAL

    @pytest.mark.parametrize(
        "exc",
        [
            socket.timeout("timed out"),
            TimeoutError("timed out"),
            ConnectionError("reset"),
            ConnectionResetError("reset by peer"),
            urllib.error.URLError("no route to host"),
        ],
    )
    def test_a_transport_failure_is_retryable(self, exc: Exception) -> None:
        assert classify(exc) is Retryability.RETRYABLE

    @pytest.mark.parametrize(
        "name",
        [
            "RateLimitError",
            "APIConnectionError",
            "APITimeoutError",
            "InternalServerError",
            "ServiceUnavailable",
            "OverloadedError",
        ],
    )
    def test_a_transient_sounding_class_name_is_retryable(self, name: str) -> None:
        """No SDK is installed, so the class name is all we have to go on."""
        assert classify(_named(name)) is Retryability.RETRYABLE

    @pytest.mark.parametrize(
        "name",
        ["AuthenticationError", "PermissionDeniedError", "NotFoundError", "BadRequestError"],
    )
    def test_a_terminal_sounding_class_name_is_terminal(self, name: str) -> None:
        assert classify(_named(name)) is Retryability.TERMINAL

    def test_an_unrecognisable_error_is_unknown_and_still_retried(self) -> None:
        """The deliberate default: most errors we cannot name are transient, and
        being wrong costs a couple of sleeps rather than a lost run."""
        assert classify(RuntimeError("who knows")) is Retryability.UNKNOWN
        assert Retryability.UNKNOWN.should_retry is True
        assert Retryability.RETRYABLE.should_retry is True
        assert Retryability.TERMINAL.should_retry is False

    def test_a_non_numeric_code_is_not_mistaken_for_a_status(self) -> None:
        exc = RuntimeError("nope")
        exc.code = "invalid_api_key"  # type: ignore[attr-defined]
        assert classify(exc) is Retryability.UNKNOWN


class RetryAfterTests:
    def test_seconds_form_is_read(self) -> None:
        exc = FakeAPIError(429, {"Retry-After": "30"})
        assert retry_after_seconds(exc) == 30.0

    def test_http_date_form_is_read(self) -> None:
        exc = FakeAPIError(429, {"Retry-After": formatdate(timeval=None, usegmt=True)})
        # "now" as a date means wait ~nothing, not "no header".
        assert retry_after_seconds(exc) == pytest.approx(0.0, abs=2.0)

    def test_a_future_http_date_becomes_a_duration(self) -> None:
        exc = FakeAPIError(429, {"Retry-After": formatdate(time.time() + 30, usegmt=True)})
        assert 25.0 <= retry_after_seconds(exc) <= 30.0

    def test_a_past_http_date_never_goes_negative(self) -> None:
        exc = FakeAPIError(429, {"Retry-After": formatdate(time.time() - 600, usegmt=True)})
        assert retry_after_seconds(exc) == 0.0

    def test_the_lookup_is_case_insensitive(self) -> None:
        assert retry_after_seconds(FakeAPIError(429, {"retry-after": "5"})) == 5.0

    def test_a_header_on_the_exception_itself_is_found(self) -> None:
        """urllib hangs headers on the error, not on a `.response`."""
        headers = email.message.Message()
        headers["Retry-After"] = "12"
        exc = urllib.error.HTTPError("http://x", 429, "Too Many", headers, None)
        assert retry_after_seconds(exc) == 12.0

    def test_no_header_means_no_opinion(self) -> None:
        assert retry_after_seconds(FakeAPIError(429)) is None
        assert retry_after_seconds(RuntimeError("bare")) is None

    def test_an_unparseable_value_is_ignored_rather_than_guessed(self) -> None:
        assert retry_after_seconds(FakeAPIError(429, {"Retry-After": "soon"})) is None


class SleepForTests:
    def test_the_delay_never_exceeds_its_ceiling(self) -> None:
        rng = random.Random(1234)
        for attempt in range(6):
            ceiling = min(MAX_SLEEP_S, 2.0 * 2**attempt)
            for _ in range(200):
                delay = sleep_for(attempt, 2.0, None, rng)
                assert 0.0 <= delay <= ceiling

    def test_the_delay_actually_varies(self) -> None:
        """Full jitter is the whole point: identical sleeps re-synchronise the pool."""
        rng = random.Random(7)
        draws = {sleep_for(3, 2.0, None, rng) for _ in range(50)}
        assert len(draws) > 1

    def test_the_window_widens_with_each_attempt(self) -> None:
        rng = random.Random(99)
        early = [sleep_for(0, 2.0, None, rng) for _ in range(200)]
        late = [sleep_for(3, 2.0, None, rng) for _ in range(200)]

        assert max(early) <= 2.0
        assert max(late) > 2.0

    def test_a_retry_after_is_honoured_instead_of_the_backoff(self) -> None:
        rng = random.Random(3)
        for _ in range(50):
            delay = sleep_for(0, 2.0, 5.0, rng)
            # Wait at least as long as we were told, plus a little to break the herd.
            assert 5.0 <= delay <= 6.0

    def test_an_absurd_retry_after_is_capped_rather_than_obeyed(self) -> None:
        """An hour-long wait inside one worker would hang the run."""
        assert sleep_for(0, 2.0, 3600.0, random.Random(0)) == MAX_SLEEP_S

    def test_the_backoff_is_capped_too(self) -> None:
        rng = random.Random(0)
        assert all(sleep_for(20, 2.0, None, rng) <= MAX_SLEEP_S for _ in range(100))

    def test_a_huge_retry_count_cannot_overflow_the_exponent(self) -> None:
        assert 0.0 <= sleep_for(5000, 2.0, None, random.Random(0)) <= MAX_SLEEP_S

    def test_a_zero_backoff_asks_for_no_sleep(self) -> None:
        assert sleep_for(4, 0.0, None, random.Random(0)) == 0.0


class FakeConnector:
    """Counts calls, fails on demand. Stands in for a provider."""

    provider = "fake"

    def __init__(self, exc: Exception, succeed_after: int | None = None) -> None:
        self.exc = exc
        self.succeed_after = succeed_after
        self.calls = 0

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls += 1
        if self.succeed_after is not None and self.calls > self.succeed_after:
            return GenerationResult(text="ok", model="fake")
        raise self.exc


@pytest.fixture()
def retrying_runner(tmp_path: Path) -> ArenaRunner:
    """A runner configured for two retries and a backoff too small to notice."""
    root = write_project(
        tmp_path / "retrying",
        {
            "project": "retrying",
            "models": [{"key": "m", "model": "mock:oracle"}],
            "run": {"trials": 1, "retries": 2, "retry_backoff_s": 0.001},
            "metrics": {"weights": {"accuracy": 1.0}},
            "output": {"dir": "results", "formats": []},
        },
        [{"id": "t1", "input": "say alpha", "reference": "alpha"}],
    )
    return ArenaRunner.from_project(root)


@pytest.fixture()
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record what the runner would have slept, without spending the time."""
    recorded: list[float] = []
    monkeypatch.setattr(runner_module.time, "sleep", recorded.append)
    return recorded


class RetryLoopTests:
    def test_a_terminal_error_is_attempted_exactly_once(
        self, retrying_runner: ArenaRunner, sleeps: list[float]
    ) -> None:
        """A 401 is not going to become a 200; failing now is the useful answer."""
        connector = FakeConnector(FakeAPIError(401, message="invalid x-api-key"))

        generation, error, attempts = retrying_runner._generate_with_retries(
            connector, GenerationRequest(messages=[{"role": "user", "content": "hi"}])
        )

        assert connector.calls == 1
        assert attempts == 1
        assert generation is None
        assert "invalid x-api-key" in error
        assert sleeps == []

    def test_a_retryable_error_uses_every_attempt(
        self, retrying_runner: ArenaRunner, sleeps: list[float]
    ) -> None:
        connector = FakeConnector(FakeAPIError(429, message="slow down"))

        generation, error, attempts = retrying_runner._generate_with_retries(
            connector, GenerationRequest(messages=[{"role": "user", "content": "hi"}])
        )

        assert connector.calls == 3          # retries=2, so three attempts
        assert attempts == 3
        assert generation is None
        assert "slow down" in error
        assert len(sleeps) == 2              # no sleep after the last attempt

    def test_an_unclassifiable_error_is_retried(
        self, retrying_runner: ArenaRunner, sleeps: list[float]
    ) -> None:
        """Documents the deliberate default — UNKNOWN gets the benefit of the doubt."""
        connector = FakeConnector(RuntimeError("something odd"))

        _, _, attempts = retrying_runner._generate_with_retries(
            connector, GenerationRequest(messages=[{"role": "user", "content": "hi"}])
        )

        assert connector.calls == 3
        assert attempts == 3

    def test_a_recovered_call_reports_how_many_attempts_it_took(
        self, retrying_runner: ArenaRunner, sleeps: list[float]
    ) -> None:
        connector = FakeConnector(FakeAPIError(503), succeed_after=1)

        generation, error, attempts = retrying_runner._generate_with_retries(
            connector, GenerationRequest(messages=[{"role": "user", "content": "hi"}])
        )

        assert generation is not None and generation.text == "ok"
        assert error is None
        assert attempts == 2
        assert len(sleeps) == 1

    def test_retry_after_drives_the_wait(
        self, retrying_runner: ArenaRunner, sleeps: list[float]
    ) -> None:
        """The provider said 3 seconds; the configured 0.001s backoff must not win."""
        connector = FakeConnector(FakeAPIError(429, {"Retry-After": "3"}))

        retrying_runner._generate_with_retries(
            connector, GenerationRequest(messages=[{"role": "user", "content": "hi"}])
        )

        assert len(sleeps) == 2
        assert all(3.0 <= slept <= 4.0 for slept in sleeps)

    def test_concurrent_workers_do_not_sleep_in_lockstep(
        self, retrying_runner: ArenaRunner, sleeps: list[float]
    ) -> None:
        """The thundering herd: without jitter every one of these is identical."""
        for _ in range(8):
            retrying_runner._generate_with_retries(
                FakeConnector(FakeAPIError(429)),
                GenerationRequest(messages=[{"role": "user", "content": "hi"}]),
            )

        assert len(set(sleeps)) > 1


PIPELINE = '''
class RateLimitError(Exception):
    """Named the way a provider SDK names it — nothing imports the SDK."""


calls = {"n": 0}


def flaky(prompt):
    calls["n"] += 1
    if calls["n"] < 3:
        raise RateLimitError("429 rate limited")
    return "alpha"


class AuthenticationError(Exception):
    pass


def bad_key(prompt):
    calls["auth"] = calls.get("auth", 0) + 1
    raise AuthenticationError("invalid api key")
'''


class EndToEndTests:
    """The run-level behaviour, through a real project and a real run."""

    def _project(self, root: Path, run_spec: str) -> Path:
        write_project(
            root,
            {
                "project": "retry-e2e",
                "targets": [{"key": "flaky", "run": run_spec}],
                "run": {"trials": 1, "retries": 2, "retry_backoff_s": 0.001},
                "metrics": {"weights": {"accuracy": 1.0}},
                "output": {"dir": "results", "formats": []},
            },
            [{"id": "t1", "input": "say alpha", "reference": "alpha"}],
        )
        (root / "pipe.py").write_text(textwrap.dedent(PIPELINE), encoding="utf-8")
        return root

    def test_a_transient_failure_still_recovers_within_the_run(self, tmp_path: Path) -> None:
        root = self._project(tmp_path / "recovers", "pipe.py:flaky")

        result = ArenaRunner.from_project(root).run()

        assert result.error_count == 0
        assert result.results[0].attempts == 3
        assert result.leaderboard.get("flaky").raw("accuracy") == 1.0

    def test_a_bad_key_fails_the_call_on_the_first_attempt(self, tmp_path: Path) -> None:
        root = self._project(tmp_path / "badkey", "pipe.py:bad_key")

        result = ArenaRunner.from_project(root).run()

        assert result.error_count == 1
        assert result.results[0].attempts == 1
        assert "invalid api key" in (result.results[0].error or "")
