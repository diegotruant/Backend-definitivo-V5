"""Rate limiter bucket lifecycle tests."""

from __future__ import annotations

from collections import deque

from api.app import _InMemoryRateLimiter


def test_rate_limiter_enforces_sliding_window() -> None:
    limiter = _InMemoryRateLimiter(max_requests=2, window_seconds=60.0)
    now = 1000.0
    assert limiter.allow("k1", now=now) is True
    assert limiter.allow("k1", now=now + 1) is True
    assert limiter.allow("k1", now=now + 2) is False


def test_rate_limiter_drops_expired_bucket_for_key() -> None:
    limiter = _InMemoryRateLimiter(max_requests=2, window_seconds=10.0)
    assert limiter.allow("client-a", now=100.0)
    assert "client-a" in limiter._buckets

    # Window slid past the only timestamp; bucket should be recycled, not grow stale entries.
    assert limiter.allow("client-a", now=111.0) is True
    assert list(limiter._buckets["client-a"]) == [111.0]


def test_prune_stale_buckets_removes_cooled_down_keys() -> None:
    limiter = _InMemoryRateLimiter(max_requests=5, window_seconds=10.0)
    limiter._buckets["stale"] = deque([100.0])
    limiter._buckets["active"] = deque([195.0])

    limiter._prune_stale_buckets(cutoff=190.0)

    assert "stale" not in limiter._buckets
    assert "active" in limiter._buckets


def test_periodic_prune_limits_bucket_map_growth() -> None:
    limiter = _InMemoryRateLimiter(max_requests=5, window_seconds=10.0)
    limiter._PRUNE_EVERY = 5

    for index in range(4):
        limiter.allow(f"key-{index}", now=100.0)

    assert len(limiter._buckets) == 4

    # 5th call triggers global prune with cutoff=190; cooled-down keys are removed.
    limiter.allow("fresh", now=200.0)

    assert len(limiter._buckets) == 1
    assert "fresh" in limiter._buckets
