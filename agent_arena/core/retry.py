"""Deciding whether a failed call is worth trying again, and for how long.

A retry loop is only as useful as its classification. Retrying a 401 turns an
instant, obvious failure — *your API key is wrong* — into a slow, confusing
one, while not retrying a 429 throws away a run that would have finished. And
because the runner calls providers from a thread pool, workers that hit the
same rate limit must back off by *different* amounts; identical sleeps bring
them all back at the same instant to hit the same limit again.

Nothing here imports a provider SDK. Every SDK in this codebase imports lazily
(AGENTS.md, invariant 1), so an ``anthropic`` or ``openai`` exception has to be
recognised without ``import anthropic``. Those exceptions are recognisable
anyway: they carry an HTTP status code on one of a few well-known attributes,
and their class names say what went wrong. That is what we inspect.

The three pieces are separate so each can be tested on its own::

    kind = classify(exc)                 # retry this, or give up now?
    wait = sleep_for(attempt, backoff_s, retry_after_seconds(exc), rng)
"""

from __future__ import annotations

import socket
import urllib.error
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from random import Random
from typing import Any

MAX_SLEEP_S = 60.0
"""Ceiling on any single backoff, including one the provider asked for.

An hour-long ``Retry-After`` is a real thing to receive, but honouring it would
park a worker — and, at the end of the run, the whole run — for an hour. We
wait at most a minute and let the attempt fail, which is a result the user can
see and act on rather than a hang."""

RETRY_AFTER_JITTER_S = 1.0
"""Spread added on top of a ``Retry-After``. The provider tells every rate-limited
worker the same number, so obeying it exactly would re-synchronise them."""

# 408 request timeout, 409 conflict, 425 too early, 429 rate limited: all mean
# "the same request may work later". Everything from 500 up is the provider's
# problem, not the request's.
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429})

# Bad request, bad key, forbidden, missing model, unprocessable body. Each of
# these will fail identically on the next call; sleeping first only hides why.
_TERMINAL_STATUS = frozenset({400, 401, 403, 404, 422})

_RETRYABLE_NAMES = (
    "TimeoutError",
    "ConnectionError",
    "APIConnectionError",
    "RateLimitError",
    "InternalServerError",
    "ServiceUnavailable",
    "ServiceUnavailableError",
    "Overloaded",
    "OverloadedError",
)

_TERMINAL_NAMES = (
    "AuthenticationError",
    "PermissionDeniedError",
    "PermissionError",
    "NotFoundError",
    "BadRequestError",
    "InvalidRequestError",
    "UnprocessableEntityError",
)


class Retryability(Enum):
    """What we concluded about a failed call."""

    RETRYABLE = "retryable"
    TERMINAL = "terminal"
    UNKNOWN = "unknown"

    @property
    def should_retry(self) -> bool:
        """UNKNOWN retries, deliberately.

        The errors we cannot classify are overwhelmingly transient — a socket
        reset, a proxy hiccup, a provider wrapper we have not met. Guessing
        "retryable" costs a couple of sleeps when we are wrong; guessing
        "terminal" fails a run that would have succeeded. Only an error that
        positively identifies itself as terminal stops the loop.
        """
        return self is not Retryability.TERMINAL


def classify(exc: BaseException) -> Retryability:
    """Decide whether ``exc`` is worth another attempt, without importing any SDK."""
    status = _status_code(exc)
    if status is not None:
        if status in _TERMINAL_STATUS:
            return Retryability.TERMINAL
        if status in _RETRYABLE_STATUS or 500 <= status <= 599:
            return Retryability.RETRYABLE
        if 400 <= status <= 499:
            # Any other 4xx still says "your request is wrong", and the request
            # we would send again is byte-for-byte the one that was rejected.
            return Retryability.TERMINAL

    if isinstance(exc, (TimeoutError, ConnectionError, socket.timeout, urllib.error.URLError)):
        return Retryability.RETRYABLE

    name = type(exc).__name__
    if name.endswith(_RETRYABLE_NAMES):
        return Retryability.RETRYABLE
    if name.endswith(_TERMINAL_NAMES):
        return Retryability.TERMINAL
    return Retryability.UNKNOWN


def retry_after_seconds(exc: BaseException) -> float | None:
    """How long the provider asked us to wait, or ``None`` if it did not say.

    ``Retry-After`` (RFC 9110) has two forms and both turn up: LLM providers
    usually send a number of seconds, while a CDN or proxy in front of one
    tends to send an HTTP date.
    """
    raw = _header(exc, "retry-after")
    if raw is None:
        return None

    text = str(raw).strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        pass

    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        # A date with no zone is UTC by the spec ("-0000").
        when = when.replace(tzinfo=timezone.utc)
    # A date already in the past means "go now", not "go backwards".
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def sleep_for(
    attempt: int,
    backoff_s: float,
    retry_after: float | None = None,
    rng: Random | None = None,
) -> float:
    """Seconds to wait after the 0-based ``attempt`` that just failed.

    Full jitter: a uniform draw from ``[0, ceiling]`` rather than the ceiling
    itself. A deterministic backoff keeps every worker that hit one rate limit
    perfectly in step — they wake together and hit it together — and spreading
    them across the whole window is what breaks that up.

    ``rng`` is a parameter rather than the module-level ``random`` so the
    caller owns the sequence and a test can seed it.
    """
    rng = rng or Random()

    if retry_after is not None:
        # The provider knows when its limit lifts; we only add enough jitter to
        # keep the workers it rate-limited together from returning together.
        return min(MAX_SLEEP_S, max(0.0, retry_after) + rng.uniform(0.0, RETRY_AFTER_JITTER_S))

    # Past ~32 doublings MAX_SLEEP_S decides the answer regardless, and clamping
    # the exponent keeps a large `run.retries` from overflowing the multiply.
    doublings = min(max(attempt, 0), 32)
    ceiling = max(0.0, min(MAX_SLEEP_S, backoff_s * 2**doublings))
    return rng.uniform(0.0, ceiling)


def _status_code(exc: BaseException) -> int | None:
    """The HTTP status behind an exception, wherever the SDK hung it.

    ``openai`` and ``anthropic`` put it on ``status_code``; an ``httpx``-backed
    error carries it on ``.response``; ``urllib.error.HTTPError`` calls it
    ``code``.
    """
    response = getattr(exc, "response", None)
    for candidate in (
        getattr(exc, "status_code", None),
        getattr(response, "status_code", None),
        getattr(response, "status", None),
        getattr(exc, "code", None),
    ):
        status = _as_status(candidate)
        if status is not None:
            return status
    return None


def _as_status(value: Any) -> int | None:
    # `code` is a string on several SDKs ("invalid_api_key", "ECONNRESET"), so
    # anything that is not a plausible HTTP status is not a status at all.
    try:
        status = int(value)
    except (TypeError, ValueError):
        return None
    return status if 100 <= status <= 599 else None


def _header(exc: BaseException, name: str) -> str | None:
    """Case-insensitive header lookup across the shapes providers use.

    ``httpx`` and ``urllib`` both hand back case-insensitive mappings, but an
    exception may just as easily carry a plain ``dict``, which is not.
    """
    for source in (getattr(exc, "response", None), exc):
        headers = getattr(source, "headers", None)
        if not hasattr(headers, "items"):
            continue
        for key, value in headers.items():
            if str(key).lower() == name:
                return value
    return None
