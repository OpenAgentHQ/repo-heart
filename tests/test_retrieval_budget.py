"""Tests for repoheart.retrieval.budget."""

from __future__ import annotations

import time

import pytest

from repoheart.config.schema import LimitsConfig
from repoheart.retrieval.budget import BudgetExceededError, ContextBudget, RunBudget


def _limits(llm: int = 10, files: int = 50, runtime: int = 600) -> LimitsConfig:
    return LimitsConfig(max_llm_calls=llm, max_files_read=files, max_runtime_seconds=runtime)


class TestContextBudget:
    def test_frozen(self) -> None:
        b = ContextBudget(max_tokens=1000, max_files=10)
        with pytest.raises((AttributeError, TypeError)):
            b.max_tokens = 999  # type: ignore[misc]

    def test_defaults(self) -> None:
        b = ContextBudget(max_tokens=500, max_files=5)
        assert b.max_chunks_per_file == 10
        assert b.priority == []


class TestRunBudget:
    def test_charge_llm_calls_ok(self) -> None:
        b = RunBudget(limits=_limits(llm=3))
        b.charge_llm_call()
        b.charge_llm_call()
        b.charge_llm_call()
        # 3 calls at ceiling of 3 should still be ok
        assert b._llm_calls == 3

    def test_charge_llm_calls_exceeds(self) -> None:
        b = RunBudget(limits=_limits(llm=2))
        b.charge_llm_call()
        b.charge_llm_call()
        with pytest.raises(BudgetExceededError, match="max_llm_calls"):
            b.charge_llm_call()

    def test_charge_files_read_ok(self) -> None:
        b = RunBudget(limits=_limits(files=5))
        b.charge_files_read(5)
        assert b._files_read == 5

    def test_charge_files_read_exceeds(self) -> None:
        b = RunBudget(limits=_limits(files=3))
        b.charge_files_read(3)
        with pytest.raises(BudgetExceededError, match="max_files_read"):
            b.charge_files_read(1)

    def test_charge_files_read_batch(self) -> None:
        b = RunBudget(limits=_limits(files=10))
        b.charge_files_read(5)
        b.charge_files_read(5)
        with pytest.raises(BudgetExceededError):
            b.charge_files_read(1)

    def test_remaining_files(self) -> None:
        b = RunBudget(limits=_limits(files=10))
        assert b.remaining_files() == 10
        b.charge_files_read(3)
        assert b.remaining_files() == 7

    def test_remaining_files_never_negative(self) -> None:
        b = RunBudget(limits=_limits(files=2))
        b.charge_files_read(2)
        # at ceiling — remaining is 0, not negative
        assert b.remaining_files() == 0

    def test_check_runtime_ok(self) -> None:
        b = RunBudget(limits=_limits(runtime=600))
        b.check_runtime()  # should not raise

    def test_check_runtime_exceeded(self) -> None:
        b = RunBudget(limits=_limits(runtime=0))
        time.sleep(0.01)
        with pytest.raises(BudgetExceededError, match="max_runtime_seconds"):
            b.check_runtime()

    def test_to_context_budget(self) -> None:
        b = RunBudget(limits=_limits(files=10))
        b.charge_files_read(3)
        cb = b.to_context_budget(max_tokens=5000, priority=["src/"])
        assert cb.max_tokens == 5000
        assert cb.max_files == 7
        assert cb.priority == ["src/"]

    def test_to_context_budget_no_priority(self) -> None:
        b = RunBudget(limits=_limits(files=10))
        cb = b.to_context_budget(max_tokens=1000)
        assert cb.priority == []

    def test_elapsed_seconds(self) -> None:
        b = RunBudget(limits=_limits())
        time.sleep(0.05)
        assert b.elapsed_seconds() >= 0.04

    def test_reset_independent(self) -> None:
        b1 = RunBudget(limits=_limits(llm=2))
        b2 = RunBudget(limits=_limits(llm=2))
        b1.charge_llm_call()
        assert b2._llm_calls == 0
