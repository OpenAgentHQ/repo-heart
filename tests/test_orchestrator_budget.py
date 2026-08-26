"""Tests for Phase 5 budget enforcement in Orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repoheart.config.schema import LimitsConfig, ProviderConfig, RepoHeartConfig, ScaleConfig
from repoheart.events.types import InternalEvent
from repoheart.git_ops.repo import GitRepo
from repoheart.github_ops.client import GitHubClient
from repoheart.idempotency.markers import IdempotencyMarkers
from repoheart.observability.logger import StructuredLogger
from repoheart.orchestrator.orchestrator import Orchestrator, _BudgetedProvider
from repoheart.providers.base import CompletionRequest
from repoheart.providers.mock import CannedResponse, MockProvider
from repoheart.retrieval.budget import BudgetExceededError, RunBudget
from repoheart.safety.gate import SafetyGate

_SAMPLE_PAYLOAD = json.loads(
    Path("examples/issues.opened.json").read_text(encoding="utf-8")
)
_SAMPLE_EVENT = InternalEvent(
    event_name="issues",
    action="opened",
    repo_full_name="example-org/example-repo",
    payload=_SAMPLE_PAYLOAD,
    sender_login="example-contributor",
)


def _make_config(
    llm_calls: int = 30,
    files: int = 200,
    runtime: int = 600,
) -> RepoHeartConfig:
    limits = LimitsConfig(
        max_llm_calls=llm_calls,
        max_files_read=files,
        max_runtime_seconds=runtime,
    )
    return RepoHeartConfig(
        provider=ProviderConfig(name="opencode"),
        scale=ScaleConfig(limits=limits),
    )


def _make_orchestrator(
    config: RepoHeartConfig | None = None,
    token: str = "",
) -> Orchestrator:
    cfg = config or _make_config()
    mock_client = MagicMock(spec=GitHubClient)
    mock_client._token = token
    mock_client.get_issue_comments.return_value = []
    mock_git = MagicMock(spec=GitRepo)
    log = StructuredLogger()
    gate = SafetyGate(config=cfg, logger=log)
    markers = IdempotencyMarkers(client=mock_client, logger=log)
    return Orchestrator(
        config=cfg,
        github_client=mock_client,
        git_repo=mock_git,
        safety_gate=gate,
        markers=markers,
        logger=log,
    )


class TestRunBudgetReset:
    def test_run_budget_initialised_on_run(self) -> None:
        orch = _make_orchestrator()
        assert orch._run_budget is None
        orch.run(_SAMPLE_EVENT, [])
        assert orch._run_budget is not None

    def test_run_budget_reset_each_call(self) -> None:
        orch = _make_orchestrator()
        orch.run(_SAMPLE_EVENT, [])
        budget_1 = orch._run_budget
        orch.run(_SAMPLE_EVENT, [])
        budget_2 = orch._run_budget
        assert budget_1 is not budget_2


class TestBudgetedProvider:
    def _inner(self) -> MockProvider:
        return MockProvider(default_response=CannedResponse("ok"))

    def _budget(self, llm: int = 5) -> RunBudget:
        return RunBudget(
            limits=LimitsConfig(max_llm_calls=llm, max_files_read=10, max_runtime_seconds=60)
        )

    def test_complete_charges_budget(self) -> None:
        budget = self._budget()
        provider = _BudgetedProvider(self._inner(), budget)
        req = CompletionRequest(messages=[], model="mock")
        provider.complete(req)
        assert budget._llm_calls == 1

    def test_complete_raises_when_ceiling_exceeded(self) -> None:
        budget = self._budget(llm=0)
        provider = _BudgetedProvider(self._inner(), budget)
        req = CompletionRequest(messages=[], model="mock")
        with pytest.raises(BudgetExceededError):
            provider.complete(req)

    def test_supports_tools_delegates(self) -> None:
        provider = _BudgetedProvider(self._inner(), self._budget())
        assert isinstance(provider.supports_tools(), bool)

    def test_provider_name_delegates(self) -> None:
        provider = _BudgetedProvider(self._inner(), self._budget())
        assert provider.provider_name() == self._inner().provider_name()


class TestRuntimeCeilingBreaksLoop:
    def test_runtime_zero_breaks_agent_loop(self) -> None:
        # max_runtime_seconds=0 means "already exceeded" the moment the budget is created
        # (uses >= semantics so 0 seconds always triggers on the first check)
        orch = _make_orchestrator(config=_make_config(runtime=0))
        summary = orch.run(_SAMPLE_EVENT, ["issue_triage", "duplicate_detection"])
        # At least one error recorded for budget exceeded
        assert any("budget" in e.lower() or "max_runtime" in e.lower() for e in summary.errors)


class TestRetrievalContextNotInRunBudget:
    def test_retrieval_context_not_exposed_via_run_budget(self) -> None:
        budget = RunBudget(
            limits=LimitsConfig(max_llm_calls=5, max_files_read=10, max_runtime_seconds=60)
        )
        assert not hasattr(budget, "retrieval_context")

    def test_agent_context_retrieval_context_defaults_none(self) -> None:
        from repoheart.orchestrator.agent_context import AgentContext
        ctx = AgentContext(event=_SAMPLE_EVENT, config=_make_config())
        assert ctx.retrieval_context is None
