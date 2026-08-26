"""Rate-limit and budget ceiling stress tests.

Covers:
1. RateLimiter token-bucket throttle (mock time)
2. max_llm_calls ceiling enforced by RunBudget / _BudgetedProvider
3. _retry_with_backoff: success after transient failures and exhaustion
4. Files-read and runtime ceilings
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from repoheart.github_ops.budgeter import RateLimiter
from repoheart.providers.base import (
    CompletionRequest,
    Message,
    ProviderRateLimitError,
    _retry_with_backoff,
)
from repoheart.providers.mock import CannedResponse, MockProvider
from repoheart.retrieval.budget import BudgetExceededError, LimitsConfig, RunBudget

# ---------------------------------------------------------------------------
# 1. Token-bucket throttle
# ---------------------------------------------------------------------------


def test_rate_limiter_starts_full() -> None:
    limiter = RateLimiter(capacity=100, refill_rate=100 / 3600)
    snap = limiter.snapshot()
    assert snap.remaining == 100


def test_rate_limiter_decrements_on_acquire() -> None:
    limiter = RateLimiter(capacity=100, refill_rate=100 / 3600)
    limiter.acquire(10)
    snap = limiter.snapshot()
    assert snap.remaining == 90


def test_rate_limiter_update_from_headers_sets_remaining() -> None:
    limiter = RateLimiter(capacity=5000)
    limiter.update_from_headers({"X-RateLimit-Remaining": "42"})
    snap = limiter.snapshot()
    assert snap.remaining == 42


def test_rate_limiter_update_ignores_bad_headers() -> None:
    limiter = RateLimiter(capacity=100)
    limiter.update_from_headers({"X-RateLimit-Remaining": "not-a-number"})
    snap = limiter.snapshot()
    assert snap.remaining == 100  # unchanged


def test_rate_limiter_used_counter_increments() -> None:
    limiter = RateLimiter(capacity=50, refill_rate=50 / 3600)
    limiter.acquire(5)
    limiter.acquire(3)
    snap = limiter.snapshot()
    assert snap.used == 8


# ---------------------------------------------------------------------------
# 2. max_llm_calls ceiling via RunBudget + _BudgetedProvider
# ---------------------------------------------------------------------------


def test_run_budget_raises_after_llm_ceiling() -> None:
    limits = LimitsConfig(max_llm_calls=2, max_files_read=100, max_runtime_seconds=600)
    budget = RunBudget(limits=limits)
    budget.charge_llm_call()
    budget.charge_llm_call()
    with pytest.raises(BudgetExceededError, match="max_llm_calls"):
        budget.charge_llm_call()


def test_budgeted_provider_enforces_max_llm_calls() -> None:
    """_BudgetedProvider must propagate BudgetExceededError once ceiling is hit."""
    from repoheart.orchestrator.orchestrator import _BudgetedProvider

    inner = MockProvider(default_response=CannedResponse('{"ok": true}'))
    limits = LimitsConfig(max_llm_calls=2, max_files_read=100, max_runtime_seconds=600)
    budget = RunBudget(limits=limits)
    budgeted = _BudgetedProvider(inner=inner, budget=budget)

    req = CompletionRequest(
        messages=[Message(role="user", content="hello")],
        model="test",
    )
    budgeted.complete(req)  # call 1
    budgeted.complete(req)  # call 2
    with pytest.raises(BudgetExceededError):
        budgeted.complete(req)  # call 3 blocked

    assert inner.call_count == 2  # inner was only called twice


# ---------------------------------------------------------------------------
# 3. _retry_with_backoff — success after transient failures
# ---------------------------------------------------------------------------


def test_retry_succeeds_after_transient_failures() -> None:
    call_count = 0

    def flaky() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ProviderRateLimitError("429")
        return "ok"

    with patch("repoheart.providers.base.time.sleep"):
        result = _retry_with_backoff(
            flaky,
            max_retries=5,
            base_delay=0.01,
            exceptions=(ProviderRateLimitError,),
        )

    assert result == "ok"
    assert call_count == 3


def test_retry_raises_after_max_retries_exhausted() -> None:
    def always_fails() -> str:
        raise ProviderRateLimitError("429")

    with patch("repoheart.providers.base.time.sleep"), pytest.raises(ProviderRateLimitError):
        _retry_with_backoff(
            always_fails,
            max_retries=2,
            base_delay=0.01,
            exceptions=(ProviderRateLimitError,),
        )


def test_retry_does_not_swallow_non_transient_errors() -> None:
    def raises_value_error() -> str:
        raise ValueError("logic error")

    # Only ProviderRateLimitError is in the retry set — ValueError must propagate immediately
    with (
        patch("repoheart.providers.base.time.sleep"),
        pytest.raises(ValueError, match="logic error"),
    ):
        _retry_with_backoff(
            raises_value_error,
            max_retries=5,
            base_delay=0.01,
            exceptions=(ProviderRateLimitError,),
        )


# ---------------------------------------------------------------------------
# 4. Files-read and runtime ceilings
# ---------------------------------------------------------------------------


def test_run_budget_files_read_ceiling() -> None:
    limits = LimitsConfig(max_llm_calls=100, max_files_read=3, max_runtime_seconds=600)
    budget = RunBudget(limits=limits)
    budget.charge_files_read(3)
    with pytest.raises(BudgetExceededError, match="max_files_read"):
        budget.charge_files_read(1)


def test_run_budget_files_read_remaining_decrements() -> None:
    limits = LimitsConfig(max_llm_calls=100, max_files_read=10, max_runtime_seconds=600)
    budget = RunBudget(limits=limits)
    budget.charge_files_read(4)
    assert budget.remaining_files() == 6


def test_run_budget_runtime_ceiling() -> None:
    limits = LimitsConfig(max_llm_calls=100, max_files_read=100, max_runtime_seconds=1)
    budget = RunBudget(limits=limits)
    # Backdate start so elapsed > ceiling
    budget._start_time = time.monotonic() - 2  # type: ignore[attr-defined]
    with pytest.raises(BudgetExceededError, match="max_runtime_seconds"):
        budget.check_runtime()


def test_run_budget_runtime_ok_within_limit() -> None:
    limits = LimitsConfig(max_llm_calls=100, max_files_read=100, max_runtime_seconds=600)
    budget = RunBudget(limits=limits)
    budget.check_runtime()  # should not raise
