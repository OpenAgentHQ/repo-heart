"""Tests for repoheart.agents.duplicate_detection."""

from __future__ import annotations

import json

from repoheart.agents.duplicate_detection import DuplicateDetectionAgent
from repoheart.config.schema import AutomationConfig, ProviderConfig, RepoHeartConfig
from repoheart.events.types import InternalEvent
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.mock import CannedResponse, MockProvider
from repoheart.safety.policy import ActionKind

_EVENT = InternalEvent(
    event_name="issues",
    action="opened",
    repo_full_name="org/repo",
    payload={"issue": {"number": 10}},
    sender_login="user",
)

_CONFIG = RepoHeartConfig(
    provider=ProviderConfig(name="mock"),
    automation=AutomationConfig(level="auto"),
)

_ISSUE = {
    "number": 10,
    "title": "App crashes on startup",
    "body": "The application throws an exception on startup.",
}

_CANDIDATES = [
    {"number": 5, "title": "Crash on launch", "body": "App fails to start."},
    {"number": 7, "title": "Startup failure", "body": "Exception on init."},
]

_HIGH_CONF_RESPONSE = json.dumps({
    "duplicates": [
        {"number": 5, "confidence": "high", "reason": "Same crash on startup"},
    ]
})

_MEDIUM_CONF_RESPONSE = json.dumps({
    "duplicates": [
        {"number": 7, "confidence": "medium", "reason": "Similar startup issue"},
    ]
})

_NO_DUPLICATES_RESPONSE = json.dumps({"duplicates": []})


def _make_context(
    provider: MockProvider,
    issue_data: dict | None = _ISSUE,
    candidate_issues: list = _CANDIDATES,
) -> AgentContext:
    return AgentContext(
        event=_EVENT,
        config=_CONFIG,
        provider=provider,
        issue_data=issue_data,
        candidate_issues=candidate_issues,
    )


def test_high_confidence_duplicate_adds_label_and_comment() -> None:
    ctx = _make_context(MockProvider(default_response=CannedResponse(_HIGH_CONF_RESPONSE)))
    result = DuplicateDetectionAgent().run(ctx)

    kinds = {a.kind for a in result.proposed_actions}
    assert ActionKind.ADD_LABEL in kinds
    assert ActionKind.POST_COMMENT in kinds

    label_action = next(a for a in result.proposed_actions if a.kind == ActionKind.ADD_LABEL)
    assert "duplicate" in label_action.payload["labels"]


def test_medium_confidence_posts_comment_no_label() -> None:
    ctx = _make_context(MockProvider(default_response=CannedResponse(_MEDIUM_CONF_RESPONSE)))
    result = DuplicateDetectionAgent().run(ctx)

    kinds = {a.kind for a in result.proposed_actions}
    assert ActionKind.POST_COMMENT in kinds
    assert ActionKind.ADD_LABEL not in kinds


def test_no_duplicates_returns_no_actions() -> None:
    ctx = _make_context(MockProvider(default_response=CannedResponse(_NO_DUPLICATES_RESPONSE)))
    result = DuplicateDetectionAgent().run(ctx)
    assert result.proposed_actions == []


def test_no_candidates_returns_no_actions() -> None:
    ctx = _make_context(
        MockProvider(default_response=CannedResponse(_HIGH_CONF_RESPONSE)),
        candidate_issues=[],
    )
    result = DuplicateDetectionAgent().run(ctx)
    assert result.proposed_actions == []


def test_duplicate_comment_contains_idempotency_marker() -> None:
    ctx = _make_context(MockProvider(default_response=CannedResponse(_HIGH_CONF_RESPONSE)))
    result = DuplicateDetectionAgent().run(ctx)

    comment = next(a for a in result.proposed_actions if a.kind == ActionKind.POST_COMMENT)
    assert "<!-- repoheart:duplicate-check -->" in comment.payload["body"]


def test_malformed_json_returns_no_actions() -> None:
    ctx = _make_context(MockProvider(default_response=CannedResponse("invalid")))
    result = DuplicateDetectionAgent().run(ctx)
    assert result.proposed_actions == []
    assert len(result.findings) > 0


def test_no_provider_returns_no_actions() -> None:
    ctx = AgentContext(
        event=_EVENT, config=_CONFIG, issue_data=_ISSUE, candidate_issues=_CANDIDATES
    )
    result = DuplicateDetectionAgent().run(ctx)
    assert result.proposed_actions == []


def test_risk_ceiling_not_exceeded() -> None:
    ctx = _make_context(MockProvider(default_response=CannedResponse(_HIGH_CONF_RESPONSE)))
    agent = DuplicateDetectionAgent()
    result = agent.run(ctx)
    agent.validate_ceiling(result)  # must not raise


def test_provider_called_once() -> None:
    provider = MockProvider(default_response=CannedResponse(_HIGH_CONF_RESPONSE))
    ctx = _make_context(provider)
    DuplicateDetectionAgent().run(ctx)
    assert provider.call_count == 1
