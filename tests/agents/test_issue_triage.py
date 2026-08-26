"""Tests for repoheart.agents.issue_triage."""

from __future__ import annotations

import json

from repoheart.agents.issue_triage import IssueTriageAgent
from repoheart.config.schema import AutomationConfig, ProviderConfig, RepoHeartConfig
from repoheart.events.types import InternalEvent
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.mock import CannedResponse, MockProvider
from repoheart.safety.policy import ActionKind

_EVENT = InternalEvent(
    event_name="issues",
    action="opened",
    repo_full_name="org/repo",
    payload={"issue": {"number": 1}},
    sender_login="user",
)

_CONFIG = RepoHeartConfig(
    provider=ProviderConfig(name="mock"),
    automation=AutomationConfig(level="auto"),
)

_ISSUE = {
    "number": 1,
    "title": "Crash when config file is missing",
    "body": "RepoHeart throws an exception if opencode.yml is absent.",
    "state": "open",
}

_REPO_LABELS = [
    {"name": "bug"},
    {"name": "enhancement"},
    {"name": "question"},
    {"name": "documentation"},
]

_VALID_RESPONSE = json.dumps({
    "type": "bug",
    "priority": "high",
    "component": "config",
    "labels": ["bug"],
    "summary": "Crash when config is absent — needs a graceful error.",
})


def _make_context(
    provider: MockProvider,
    issue_data: dict | None = _ISSUE,
    repo_labels: list = _REPO_LABELS,
) -> AgentContext:
    return AgentContext(
        event=_EVENT,
        config=_CONFIG,
        provider=provider,
        issue_data=issue_data,
        repo_labels=repo_labels,
    )


def test_triage_proposes_label_and_issue_comment() -> None:
    ctx = _make_context(MockProvider(default_response=CannedResponse(_VALID_RESPONSE)))
    result = IssueTriageAgent().run(ctx)

    kinds = {a.kind for a in result.proposed_actions}
    assert ActionKind.ADD_LABEL in kinds
    assert ActionKind.POST_COMMENT not in kinds
    assert result.issue_comments
    assert result.issue_comments[0].title == "Issue Triage"


def test_triage_labels_are_filtered_to_available() -> None:
    response = json.dumps({
        "type": "bug",
        "priority": "high",
        "component": None,
        "labels": ["bug", "nonexistent-label"],
        "summary": "Summary.",
    })
    ctx = _make_context(MockProvider(default_response=CannedResponse(response)))
    result = IssueTriageAgent().run(ctx)

    label_action = next(a for a in result.proposed_actions if a.kind == ActionKind.ADD_LABEL)
    assert "nonexistent-label" not in label_action.payload["labels"]
    assert "bug" in label_action.payload["labels"]


def test_triage_no_labels_skips_label_action() -> None:
    response = json.dumps({
        "type": "question",
        "priority": "low",
        "component": None,
        "labels": [],
        "summary": "Just a question.",
    })
    ctx = _make_context(MockProvider(default_response=CannedResponse(response)))
    result = IssueTriageAgent().run(ctx)

    kinds = {a.kind for a in result.proposed_actions}
    assert ActionKind.ADD_LABEL not in kinds
    assert result.issue_comments


def test_triage_issue_comment_body_contains_type_and_priority() -> None:
    ctx = _make_context(MockProvider(default_response=CannedResponse(_VALID_RESPONSE)))
    result = IssueTriageAgent().run(ctx)

    ic = result.issue_comments[0]
    assert "bug" in ic.body.lower() or "bug" in ic.body
    assert "high" in ic.body


def test_triage_malformed_json_returns_no_actions() -> None:
    ctx = _make_context(MockProvider(default_response=CannedResponse("not json at all")))
    result = IssueTriageAgent().run(ctx)

    assert result.proposed_actions == []
    assert len(result.findings) > 0
    assert "parsing failed" in result.findings[0].summary.lower()


def test_triage_no_provider_returns_no_actions() -> None:
    ctx = AgentContext(event=_EVENT, config=_CONFIG, issue_data=_ISSUE)
    result = IssueTriageAgent().run(ctx)
    assert result.proposed_actions == []


def test_triage_no_issue_data_returns_no_actions() -> None:
    ctx = _make_context(
        MockProvider(default_response=CannedResponse(_VALID_RESPONSE)), issue_data=None
    )
    result = IssueTriageAgent().run(ctx)
    assert result.proposed_actions == []


def test_triage_risk_ceiling_not_exceeded() -> None:
    ctx = _make_context(MockProvider(default_response=CannedResponse(_VALID_RESPONSE)))
    agent = IssueTriageAgent()
    result = agent.run(ctx)
    agent.validate_ceiling(result)  # must not raise


def test_triage_calls_provider_once() -> None:
    provider = MockProvider(default_response=CannedResponse(_VALID_RESPONSE))
    ctx = _make_context(provider)
    IssueTriageAgent().run(ctx)
    assert provider.call_count == 1


def test_triage_severity_maps_priority_correctly() -> None:
    ctx = _make_context(MockProvider(default_response=CannedResponse(_VALID_RESPONSE)))
    result = IssueTriageAgent().run(ctx)
    assert result.issue_comments[0].severity == "high"
