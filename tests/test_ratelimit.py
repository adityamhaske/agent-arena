"""Tests for per-provider rate limiting.

`run.concurrency` is one global number, which is the wrong shape as soon as a
run mixes a laptop running Ollama with a frontier API. A profile declares its
own ceiling and gets its own budget.

The point of limiting here is *not being throttled*, so the tests assert on
timing and on ordering rather than on internal counters: a bucket that reports
the right numbers while letting a burst through has not done its job.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from agent_arena.core.config import ProjectConfig
from agent_arena.core.ratelimit import LimiterRegistry, ProviderLimiter, TokenBucket
from agent_arena.core.runner import ArenaRunner


# ------------------------------------------------------------------- bucket


def test_a_bucket_allows_its_burst_immediately():
    bucket = TokenBucket(rate=10, capacity=5)
    started = time.monotonic()
    for _ in range(5):
        bucket.acquire()
    assert time.monotonic() - started < 0.1


def test_a_bucket_makes_the_next_caller_wait():
    bucket = TokenBucket(rate=20, capacity=2)  # 50ms per token once drained
    bucket.acquire()
    bucket.acquire()
    started = time.monotonic()
    bucket.acquire()
    assert time.monotonic() - started >= 0.03


def test_a_bucket_refills_over_time():
    bucket = TokenBucket(rate=100, capacity=2)
    bucket.acquire()
    bucket.acquire()
    time.sleep(0.05)
    started = time.monotonic()
    bucket.acquire()
    assert time.monotonic() - started < 0.02


def test_an_oversized_request_is_clamped_rather_than_deadlocking():
    # Asking for more than the bucket can ever hold would otherwise wait
    # forever, which is worse than being slightly over the limit.
    bucket = TokenBucket(rate=1000, capacity=10)
    assert bucket.acquire(1_000_000, timeout=1.0) < 1.0


def test_acquire_respects_a_timeout():
    bucket = TokenBucket(rate=1, capacity=1)
    bucket.acquire()
    started = time.monotonic()
    bucket.acquire(1.0, timeout=0.1)
    assert time.monotonic() - started < 0.5


# ------------------------------------------------------------------ limiter


def test_no_limits_means_no_overhead():
    limiter = ProviderLimiter({})
    assert limiter.active is False


def test_a_concurrency_limit_is_actually_enforced():
    limiter = ProviderLimiter({"concurrency": 2})
    peak, current = 0, 0
    lock = threading.Lock()

    def worker():
        nonlocal peak, current
        with limiter:
            with lock:
                current += 1
                peak = max(peak, current)
            time.sleep(0.05)
            with lock:
                current -= 1

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak <= 2


def test_a_limiter_records_how_long_it_made_callers_wait():
    # burst 1 means the second caller has to wait for a refill.
    limiter = ProviderLimiter({"rpm": 600, "burst": 1})
    with limiter:
        pass
    with limiter:
        pass
    assert limiter.waited_s > 0


def test_burst_defaults_to_the_whole_minute_quota():
    # A per-minute provider quota does permit spending it all at once.
    limiter = ProviderLimiter({"rpm": 60})
    assert limiter.requests.capacity == 60


def test_burst_can_be_lowered_to_smooth_traffic():
    limiter = ProviderLimiter({"rpm": 600, "burst": 5})
    assert limiter.requests.capacity == 5


def test_a_zero_or_negative_limit_is_ignored():
    assert ProviderLimiter({"rpm": 0, "concurrency": -1}).active is False


def test_a_nonsense_limit_is_ignored_rather_than_raising():
    # A settings page can produce anything; a bad value must not kill a run.
    assert ProviderLimiter({"rpm": "fast"}).active is False


# ----------------------------------------------------------------- registry


def test_the_registry_returns_one_limiter_per_profile(tmp_path):
    config = ProjectConfig.from_dict(
        {"project": "p",
         "providers": [{"id": "a", "kind": "openai", "rate_limit": {"rpm": 60}}],
         "models": [{"key": "m", "provider": "a", "model": "gpt-5"}],
         "tests": {"paths": []}},
        root=tmp_path,
    )
    registry = LimiterRegistry()
    first = registry.for_profile(config.providers[0])
    second = registry.for_profile(config.providers[0])
    assert first is second


def test_a_profile_with_no_limits_gets_no_limiter(tmp_path):
    config = ProjectConfig.from_dict(
        {"project": "p",
         "providers": [{"id": "a", "kind": "openai"}],
         "models": [{"key": "m", "provider": "a", "model": "gpt-5"}],
         "tests": {"paths": []}},
        root=tmp_path,
    )
    assert LimiterRegistry().for_profile(config.providers[0]) is None


def test_no_profile_means_no_limiter():
    assert LimiterRegistry().for_profile(None) is None


# ---------------------------------------------------------------- end to end


def test_a_rate_limited_run_reports_the_wait(tmp_path):
    (tmp_path / "tests.yaml").write_text(
        json.dumps({"tests": [{"id": f"t{i}", "input": "x", "reference": "billing"}
                              for i in range(6)]}),
        encoding="utf-8",
    )
    config = ProjectConfig.from_dict(
        {
            "project": "limited",
            "providers": [{"id": "slow", "kind": "mock", "rate_limit": {"rpm": 600, "burst": 2}}],
            "models": [{"key": "m", "provider": "slow", "model": "mock:oracle"}],
            "run": {"trials": 1, "concurrency": 4},
            "scorers": {"default": "classification",
                        "options": {"classification": {"labels": ["billing", "technical"]}}},
            "tests": ["tests.yaml"],
            "output": {"dir": "results"},
        },
        root=tmp_path,
    )
    result = ArenaRunner(config).run()
    assert len(result.results) == 6
    # Six calls at 120/min drains the burst and forces a wait, which the
    # leaderboard should explain rather than leaving the run mysteriously slow.
    assert any("rate limit" in note for note in result.leaderboard.notes)


def test_an_unlimited_run_says_nothing_about_rate_limits(tmp_path):
    (tmp_path / "tests.yaml").write_text(
        json.dumps({"tests": [{"id": "t1", "input": "x", "reference": "billing"}]}),
        encoding="utf-8",
    )
    config = ProjectConfig.from_dict(
        {"project": "free", "models": [{"key": "m", "model": "mock:oracle"}],
         "run": {"trials": 1},
         "scorers": {"default": "classification",
                     "options": {"classification": {"labels": ["billing", "technical"]}}},
         "tests": ["tests.yaml"], "output": {"dir": "results"}},
        root=tmp_path,
    )
    result = ArenaRunner(config).run()
    assert not any("rate limit" in note for note in result.leaderboard.notes)
