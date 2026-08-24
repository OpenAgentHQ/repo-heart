"""Tests for repoheart.orchestrator.orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from repoheart.agents.base import Agent, AgentResult, ProposedAction
from repoheart.agents.noop import NoOpAgent
from repoheart.agents.registry import AGENT_REGISTRY
from repoheart.config.schema import AutomationConfig, ProviderConfig, RepoHeartConfig
from repoheart.events.types import InternalEvent
from repoheart.git_ops.repo import GitRepo
from repoheart.github_ops.client import GitHubClient
from repoheart.idempotency.markers import IdempotencyMarkers
from repoheart.observability.logger import StructuredLogger
from repoheart.orchestrator.orchestrator import Orchestrator
from repoheart.safety.gate import SafetyGate
from repoheart.safety.policy import ActionKind, RiskLevel

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


def _make_config(level: str = "auto", require_human: list[str] | None = None) -> RepoHeartConfig:
    return RepoHeartConfig(
        provider=ProviderConfig(name="opencode"),
        automation=AutomationConfig(
            level=level, require_human_approval=require_human or []
        ),
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


def test_noop_agent_produces_zero_actions() -> None:
    orch = _make_orchestrator()
    summary = orch.run(_SAMPLE_EVENT, ["issue_triage"])
    assert summary.actions_taken == 0
    assert summary.actions_escalated == 0
    assert summary.actions_denied == 0
    assert not summary.errors


def test_all_three_issue_agents_run() -> None:
    orch = _make_orchestrator()
    summary = orch.run(_SAMPLE_EVENT, ["issue_triage", "duplicate_detection", "issue_resolution"])
    assert set(summary.agents_run) == {"issue_triage", "duplicate_detection", "issue_resolution"}


def test_agent_exception_does_not_abort_other_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenAgent(Agent):
        name = "broken"
        risk_level = RiskLevel.SAFE
        handles_events = ["*"]

        def run(self, context: Any) -> AgentResult:
            raise RuntimeError("broken!")

    monkeypatch.setitem(AGENT_REGISTRY, "issue_triage", _BrokenAgent)
    monkeypatch.setitem(AGENT_REGISTRY, "duplicate_detection", NoOpAgent)

    orch = _make_orchestrator()
    summary = orch.run(
        _SAMPLE_EVENT, ["issue_triage", "duplicate_detection"]
    )
    assert len(summary.errors) == 1
    assert "duplicate_detection" in summary.agents_run


def test_safe_action_taken_in_auto_mode() -> None:
    class _LabelAgent(Agent):
        name = "labeler"
        risk_level = RiskLevel.SAFE
        handles_events = ["*"]

        def run(self, context: Any) -> AgentResult:
            return AgentResult(
                proposed_actions=[
                    ProposedAction(
                        kind=ActionKind.ADD_LABEL,
                        payload={"labels": ["bug"]},
                        reason="test",
                    )
                ]
            )

    import unittest.mock

    with unittest.mock.patch.dict(AGENT_REGISTRY, {"issue_triage": _LabelAgent}):
        orch = _make_orchestrator(config=_make_config("auto", []))
        summary = orch.run(_SAMPLE_EVENT, ["issue_triage"])

    assert summary.actions_taken == 1


def test_idempotency_hit_skips_agent() -> None:
    cfg = _make_config()
    mock_client = MagicMock(spec=GitHubClient)
    mock_client._token = "tok"
    log = StructuredLogger()
    gate = SafetyGate(config=cfg, logger=log)

    # Simulate marker already recorded
    mock_markers = MagicMock(spec=IdempotencyMarkers)
    mock_markers.has_been_processed.return_value = True

    orch = Orchestrator(
        config=cfg,
        github_client=mock_client,
        git_repo=MagicMock(spec=GitRepo),
        safety_gate=gate,
        markers=mock_markers,
        logger=log,
    )
    summary = orch.run(_SAMPLE_EVENT, ["issue_triage"])
    assert "issue_triage" not in summary.agents_run


def test_unknown_agent_name_skipped_gracefully() -> None:
    orch = _make_orchestrator()
    summary = orch.run(_SAMPLE_EVENT, ["nonexistent_agent"])
    assert not summary.agents_run
    assert not summary.errors


def test_ceiling_violation_counts_as_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _OverreachingAgent(Agent):
        name = "overreach"
        risk_level = RiskLevel.SAFE
        handles_events = ["*"]

        def run(self, context: Any) -> AgentResult:
            return AgentResult(
                proposed_actions=[
                    ProposedAction(
                        kind=ActionKind.PUSH_BRANCH,
                        payload={},
                        reason="bad",
                        risk=RiskLevel.MEDIUM,
                    )
                ]
            )

    monkeypatch.setitem(AGENT_REGISTRY, "issue_triage", _OverreachingAgent)
    orch = _make_orchestrator()
    summary = orch.run(_SAMPLE_EVENT, ["issue_triage"])
    assert len(summary.errors) == 1
    assert "issue_triage" not in summary.agents_run


def test_run_summary_has_correct_event() -> None:
    orch = _make_orchestrator()
    summary = orch.run(_SAMPLE_EVENT, [])
    assert summary.event is _SAMPLE_EVENT
