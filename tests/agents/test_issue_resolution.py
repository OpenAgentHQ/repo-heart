"""Tests for repoheart.agents.issue_resolution."""

from __future__ import annotations

import json

from repoheart.agents.issue_resolution import IssueResolutionAgent
from repoheart.config.schema import AutomationConfig, ProviderConfig, RepoHeartConfig
from repoheart.events.types import InternalEvent
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.mock import CannedResponse, MockProvider
from repoheart.safety.policy import ActionKind

_EVENT = InternalEvent(
    event_name="issues",
    action="opened",
    repo_full_name="org/repo",
    payload={"issue": {"number": 20}},
    sender_login="user",
)

_CONFIG = RepoHeartConfig(
    provider=ProviderConfig(name="mock"),
    automation=AutomationConfig(level="auto"),
)

_ISSUE = {
    "number": 20,
    "title": "Crash when config file is missing",
    "body": "App throws an exception when repoheart.yml is absent.",
}

_MERGED_PR = {
    "number": 99,
    "title": "Fix crash when config is absent",
    "body": "Closes #20 — handles missing config gracefully.",
    "pull_request": {"merged_at": "2026-08-01T12:00:00Z"},
}

_OPEN_PR = {
    "number": 100,
    "title": "WIP: fix config crash",
    "body": "Fixes #20",
    "pull_request": {"merged_at": None},
}

_HIGH_CONF_RESPONSE = json.dumps({
    "resolved": True,
    "confidence": "high",
    "pr_number": 99,
    "explanation": "PR #99 adds a graceful fallback for missing config files.",
})

_MEDIUM_CONF_RESPONSE = json.dumps({
    "resolved": True,
    "confidence": "medium",
    "pr_number": 99,
    "explanation": "PR #99 likely resolves this but the fix scope is unclear.",
})

_NOT_RESOLVED_RESPONSE = json.dumps({
    "resolved": False,
    "confidence": "high",
    "pr_number": None,
    "explanation": "PR addresses a different crash.",
})


def _make_context(
    provider: MockProvider,
    issue_data: dict | None = _ISSUE,
    linked_pull_requests: list | None = None,
) -> AgentContext:
    prs = [_MERGED_PR] if linked_pull_requests is None else linked_pull_requests
    return AgentContext(
        event=_EVENT,
        config=_CONFIG,
        provider=provider,
        issue_data=issue_data,
        linked_pull_requests=prs,
    )


def test_high_confidence_produces_issue_comment_and_label() -> None:
    ctx = _make_context(MockProvider(default_response=CannedResponse(_HIGH_CONF_RESPONSE)))
    result = IssueResolutionAgent().run(ctx)

    kinds = {a.kind for a in result.proposed_actions}
    assert ActionKind.POST_COMMENT not in kinds
    assert ActionKind.ADD_LABEL in kinds
    assert result.issue_comments
    assert result.issue_comments[0].title == "Possibly already fixed"

    label_action = next(a for a in result.proposed_actions if a.kind == ActionKind.ADD_LABEL)
    assert "already-fixed" in label_action.payload["labels"]


def test_medium_confidence_produces_issue_comment_no_label() -> None:
    ctx = _make_context(MockProvider(default_response=CannedResponse(_MEDIUM_CONF_RESPONSE)))
    result = IssueResolutionAgent().run(ctx)

    kinds = {a.kind for a in result.proposed_actions}
    assert ActionKind.ADD_LABEL not in kinds
    assert result.issue_comments
    assert result.issue_comments[0].severity == "warning"


def test_not_resolved_returns_no_actions() -> None:
    ctx = _make_context(MockProvider(default_response=CannedResponse(_NOT_RESOLVED_RESPONSE)))
    result = IssueResolutionAgent().run(ctx)
    assert result.proposed_actions == []
    assert not result.issue_comments


def test_no_linked_prs_returns_no_actions() -> None:
    ctx = _make_context(
        MockProvider(default_response=CannedResponse(_HIGH_CONF_RESPONSE)),
        linked_pull_requests=[],
    )
    result = IssueResolutionAgent().run(ctx)
    assert result.proposed_actions == []


def test_open_pr_ignored() -> None:
    ctx = _make_context(
        MockProvider(default_response=CannedResponse(_HIGH_CONF_RESPONSE)),
        linked_pull_requests=[_OPEN_PR],
    )
    result = IssueResolutionAgent().run(ctx)
    assert result.proposed_actions == []


def test_high_conf_issue_comment_has_reference() -> None:
    ctx = _make_context(MockProvider(default_response=CannedResponse(_HIGH_CONF_RESPONSE)))
    result = IssueResolutionAgent().run(ctx)
    ic = result.issue_comments[0]
    assert "#99" in ic.references


def test_malformed_json_returns_no_actions() -> None:
    ctx = _make_context(MockProvider(default_response=CannedResponse("oops")))
    result = IssueResolutionAgent().run(ctx)
    assert result.proposed_actions == []
    assert len(result.findings) > 0


def test_no_provider_returns_no_actions() -> None:
    ctx = AgentContext(
        event=_EVENT, config=_CONFIG, issue_data=_ISSUE, linked_pull_requests=[_MERGED_PR]
    )
    result = IssueResolutionAgent().run(ctx)
    assert result.proposed_actions == []


def test_risk_ceiling_not_exceeded() -> None:
    ctx = _make_context(MockProvider(default_response=CannedResponse(_HIGH_CONF_RESPONSE)))
    agent = IssueResolutionAgent()
    result = agent.run(ctx)
    agent.validate_ceiling(result)  # must not raise


def test_provider_called_once() -> None:
    provider = MockProvider(default_response=CannedResponse(_HIGH_CONF_RESPONSE))
    ctx = _make_context(provider)
    IssueResolutionAgent().run(ctx)
    assert provider.call_count == 1
