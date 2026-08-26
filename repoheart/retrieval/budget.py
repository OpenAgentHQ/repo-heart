"""Budget tracking for large-repo retrieval and per-run LLM call limits.

Two objects:
  RunBudget   — mutable, lives on the Orchestrator for one run() call.
                Tracks cross-agent usage. Never placed in AgentContext.
  ContextBudget — frozen snapshot derived from RunBudget at retrieval time.
                  Passed into the retrieval layer and stored in AgentContext.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from repoheart.config.schema import LimitsConfig


class BudgetExceededError(RuntimeError):
    """Raised when any per-run ceiling is breached."""


@dataclass(frozen=True)
class ContextBudget:
    """Immutable quota handed to each retrieval call.

    Derived from RunBudget at the moment _build_context() calls the retrieval
    layer. Agents may read this (via RetrievalContext) but never mutate it.
    """

    max_tokens: int
    max_files: int
    max_chunks_per_file: int = 10
    priority: list[str] = field(default_factory=list)


@dataclass
class RunBudget:
    """Mutable per-run counters owned by the Orchestrator.

    Reset at the top of every Orchestrator.run() call. Never passed into
    AgentContext or to agent code.
    """

    limits: LimitsConfig
    _llm_calls: int = field(default=0, init=False)
    _files_read: int = field(default=0, init=False)
    _start_time: float = field(init=False)

    def __post_init__(self) -> None:
        self._start_time = time.monotonic()

    def charge_llm_call(self) -> None:
        """Increment LLM call counter; raise BudgetExceededError at ceiling."""
        self._llm_calls += 1
        if self._llm_calls > self.limits.max_llm_calls:
            raise BudgetExceededError(
                f"max_llm_calls={self.limits.max_llm_calls} exceeded "
                f"(used={self._llm_calls})"
            )

    def charge_files_read(self, n: int = 1) -> None:
        """Increment files-read counter; raise BudgetExceededError at ceiling."""
        self._files_read += n
        if self._files_read > self.limits.max_files_read:
            raise BudgetExceededError(
                f"max_files_read={self.limits.max_files_read} exceeded "
                f"(used={self._files_read})"
            )

    def check_runtime(self) -> None:
        """Raise BudgetExceededError if wall-clock time has exceeded the limit."""
        elapsed = time.monotonic() - self._start_time
        if elapsed >= self.limits.max_runtime_seconds:
            raise BudgetExceededError(
                f"max_runtime_seconds={self.limits.max_runtime_seconds} exceeded "
                f"(elapsed={elapsed:.1f}s)"
            )

    def remaining_files(self) -> int:
        return max(0, self.limits.max_files_read - self._files_read)

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._start_time

    def to_context_budget(
        self,
        max_tokens: int,
        priority: list[str] | None = None,
    ) -> ContextBudget:
        """Derive a frozen ContextBudget from current RunBudget state."""
        return ContextBudget(
            max_tokens=max_tokens,
            max_files=self.remaining_files(),
            priority=priority or [],
        )
