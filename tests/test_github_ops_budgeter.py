"""Tests for repoheart.github_ops.budgeter."""

from __future__ import annotations

import contextlib
from unittest.mock import patch

from repoheart.github_ops.budgeter import RateLimiter


def test_fresh_limiter_starts_full() -> None:
    rl = RateLimiter(capacity=100)
    snap = rl.snapshot()
    assert snap.remaining == 100


def test_acquire_decrements_remaining() -> None:
    rl = RateLimiter(capacity=100)
    rl.acquire(1)
    snap = rl.snapshot()
    assert snap.remaining == 99


def test_acquire_does_not_sleep_when_bucket_full() -> None:
    rl = RateLimiter(capacity=100)
    with patch("time.sleep") as mock_sleep:
        rl.acquire(1)
        mock_sleep.assert_not_called()


def test_acquire_sleeps_when_bucket_empty() -> None:
    rl = RateLimiter(capacity=1, refill_rate=1.0)
    rl.acquire(1)  # drain the bucket
    with patch("time.sleep") as mock_sleep:
        # After sleeping, tokens refill — simulate by patching monotonic
        import time
        original_monotonic = time.monotonic
        calls = [0]

        def fake_monotonic() -> float:
            calls[0] += 1
            # advance time by 2 seconds on the 3rd call to trigger refill
            return original_monotonic() + (2.0 if calls[0] >= 3 else 0.0)

        with (
            patch("time.monotonic", side_effect=fake_monotonic),
            contextlib.suppress(Exception),
        ):
            rl.acquire(1)
        assert mock_sleep.called


def test_update_from_headers_syncs_remaining() -> None:
    rl = RateLimiter(capacity=5000)
    rl.update_from_headers({"X-RateLimit-Remaining": "4999"})
    snap = rl.snapshot()
    assert snap.remaining == 4999


def test_update_from_headers_lowercase_keys() -> None:
    rl = RateLimiter(capacity=5000)
    rl.update_from_headers({"x-ratelimit-remaining": "3000"})
    snap = rl.snapshot()
    assert snap.remaining == 3000


def test_update_from_headers_syncs_reset_at() -> None:
    rl = RateLimiter(capacity=5000)
    rl.update_from_headers({"X-RateLimit-Reset": "9999999999"})
    snap = rl.snapshot()
    assert snap.reset_at == 9999999999.0


def test_update_from_headers_ignores_invalid_values() -> None:
    rl = RateLimiter(capacity=5000)
    before = rl.snapshot().remaining
    rl.update_from_headers({"X-RateLimit-Remaining": "not-a-number"})
    after = rl.snapshot().remaining
    assert after == before


def test_snapshot_returns_rate_limit_budget() -> None:
    from repoheart.github_ops.budgeter import RateLimitBudget

    rl = RateLimiter(capacity=50)
    snap = rl.snapshot()
    assert isinstance(snap, RateLimitBudget)
    assert snap.remaining >= 0
    assert snap.used >= 0


def test_used_counter_increments() -> None:
    rl = RateLimiter(capacity=100)
    rl.acquire(3)
    assert rl.snapshot().used == 3
