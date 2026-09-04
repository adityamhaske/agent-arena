"""Per-provider rate limiting.

`run.concurrency` is a single global number, which is the wrong shape as soon as
a run mixes providers: a laptop running Ollama and a frontier API have nothing
in common about how many requests they will take. A profile declares its own
limits and gets its own budget.

Limiting here is about *not being throttled* rather than about fairness. Going
over a provider's ceiling does not make a run faster — every rejected call comes
back as a retry with backoff, so the sweep gets slower and noisier. Waiting a
few hundred milliseconds is strictly cheaper.
"""

from __future__ import annotations

import threading
import time
from typing import Any


class TokenBucket:
    """Classic token bucket: ``rate`` units per second, burst up to ``capacity``.

    Used for both requests-per-minute and tokens-per-minute, because they are
    the same shape — only the unit differs.
    """

    __slots__ = ("rate", "capacity", "_tokens", "_updated", "_lock")

    def __init__(self, rate: float, capacity: float | None = None) -> None:
        self.rate = float(rate)
        self.capacity = float(capacity if capacity is not None else rate)
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self, now: float) -> None:
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._updated = now

    def acquire(self, amount: float = 1.0, timeout: float | None = None) -> float:
        """Block until ``amount`` is available. Returns the seconds spent waiting.

        An amount larger than the bucket can ever hold would wait forever, so it
        is clamped to the capacity — being slightly over a limit is better than
        deadlocking a run.
        """
        amount = min(float(amount), self.capacity)
        waited = 0.0
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                self._refill(now)
                if self._tokens >= amount:
                    self._tokens -= amount
                    return waited
                shortfall = amount - self._tokens
                sleep_for = shortfall / self.rate if self.rate > 0 else 0.05
            if deadline is not None and time.monotonic() + sleep_for > deadline:
                return waited
            sleep_for = min(sleep_for, 0.25)  # wake up often enough to stay fair
            time.sleep(sleep_for)
            waited += sleep_for


class ProviderLimiter:
    """The limits one provider profile declared.

    ``concurrency`` is a semaphore, ``rpm`` and ``tpm`` are buckets. All three
    are optional; an unset limit costs nothing at all.
    """

    def __init__(self, limits: dict[str, Any] | None = None) -> None:
        limits = limits or {}
        rpm = _positive(limits.get("rpm"))
        tpm = _positive(limits.get("tpm"))
        concurrency = _positive(limits.get("concurrency"))
        # How much of a minute's quota may go at once. Defaults to all of it,
        # which is what a per-minute provider quota actually permits; set it
        # lower to smooth traffic instead of spending the whole allowance in
        # the first second and then stalling.
        burst = _positive(limits.get("burst"))

        self.requests = TokenBucket(rpm / 60.0, burst or rpm) if rpm else None
        self.tokens = TokenBucket(tpm / 60.0, tpm) if tpm else None
        self.slots = threading.Semaphore(int(concurrency)) if concurrency else None
        self.waited_s = 0.0
        self._stat_lock = threading.Lock()

    @property
    def active(self) -> bool:
        return bool(self.requests or self.tokens or self.slots)

    def __enter__(self) -> ProviderLimiter:
        if self.slots is not None:
            self.slots.acquire()
        waited = 0.0
        if self.requests is not None:
            waited += self.requests.acquire(1.0)
        if self.tokens is not None:
            # Estimated, because the real count is only known after the call.
            # An estimate that is roughly right keeps a run under the ceiling;
            # waiting for certainty would mean never limiting at all.
            waited += self.tokens.acquire(self._estimate)
        if waited:
            with self._stat_lock:
                self.waited_s += waited
        return self

    def __exit__(self, *exc_info: Any) -> None:
        if self.slots is not None:
            self.slots.release()

    #: Rough tokens per call, used before the real usage is known.
    _estimate = 1000.0


def _positive(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


class LimiterRegistry:
    """One limiter per provider profile, shared across the runner's threads."""

    def __init__(self) -> None:
        self._limiters: dict[str, ProviderLimiter] = {}
        self._lock = threading.Lock()

    def for_profile(self, profile: Any) -> ProviderLimiter | None:
        if profile is None or not getattr(profile, "rate_limit", None):
            return None
        with self._lock:
            limiter = self._limiters.get(profile.id)
            if limiter is None:
                limiter = ProviderLimiter(profile.rate_limit)
                self._limiters[profile.id] = limiter
        return limiter if limiter.active else None

    def waits(self) -> dict[str, float]:
        """Seconds spent waiting per profile — worth reporting when it is large."""
        with self._lock:
            return {key: round(v.waited_s, 2) for key, v in self._limiters.items() if v.waited_s}
