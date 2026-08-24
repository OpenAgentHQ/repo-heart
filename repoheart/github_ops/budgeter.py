"""Token-bucket rate limiter for GitHub REST API calls.

GitHub REST API: 5 000 req/hr for authenticated requests (~1.39 req/s sustained).
The bucket starts full; ``update_from_headers`` keeps it honest against the
server-side counter returned in every GitHub response.
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass


@dataclass
class RateLimitBudget:
    """Immutable snapshot of rate-limit state at a point in time."""

    remaining: int
    reset_at: float
    used: int


class RateLimiter:
    """Synchronous token-bucket rate limiter.

    Args:
        capacity: Maximum tokens (one hour's allowance). Default: 5000.
        refill_rate: Tokens per second to refill. Default: 5000/3600.
    """

    def __init__(
        self,
        capacity: int = 5000,
        refill_rate: float = 5000 / 3600,
    ) -> None:
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._tokens: float = float(capacity)
        self._last_refill: float = time.monotonic()
        self._used: int = 0
        self._reset_at: float = time.time() + 3600.0

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now

    def acquire(self, tokens: int = 1) -> None:
        """Block until ``tokens`` are available, then consume them."""
        self._refill()
        while self._tokens < tokens:
            deficit = tokens - self._tokens
            sleep_secs = deficit / self._refill_rate
            time.sleep(sleep_secs)
            self._refill()
        self._tokens -= tokens
        self._used += tokens

    def update_from_headers(self, headers: dict[str, str]) -> None:
        """Sync bucket state from GitHub's ``X-RateLimit-*`` response headers."""
        remaining_str = headers.get("X-RateLimit-Remaining") or headers.get(
            "x-ratelimit-remaining"
        )
        reset_str = headers.get("X-RateLimit-Reset") or headers.get("x-ratelimit-reset")

        if remaining_str is not None:
            with contextlib.suppress(ValueError):
                self._tokens = float(int(remaining_str))

        if reset_str is not None:
            with contextlib.suppress(ValueError):
                self._reset_at = float(reset_str)

    def snapshot(self) -> RateLimitBudget:
        """Return current budget as an immutable snapshot."""
        self._refill()
        return RateLimitBudget(
            remaining=int(self._tokens),
            reset_at=self._reset_at,
            used=self._used,
        )
