"""Tests for repoheart.agents.conflict_resolution."""

from __future__ import annotations

import json

from repoheart.agents.conflict_resolution import ConflictResolutionAgent
from repoheart.config.schema import AutomationConfig, ProviderConfig, RepoHeartConfig
from repoheart.events.types import InternalEvent
from repoheart.git_ops.conflicts import ConflictBlock, ConflictFile
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.mock import CannedResponse, MockProvider
from repoheart.safety.policy import ActionKind, RiskLevel

_PR_EVENT = InternalEvent(
    event_name="pull_request",
    action="opened",
    repo_full_name="org/repo",
    payload={"pull_request": {"number": 7, "base": {"sha": "base123"}, "head": {"sha": "head456"}}},
    sender_login="dev",
)

_PUSH_EVENT = InternalEvent(
    event_name="push",
    action="",
    repo_full_name="org/repo",
    payload={"after": "deadbeef"},
    sender_login="dev",
)

_CONFIG = RepoHeartConfig(
    provider=ProviderConfig(name="mock"),
    automation=AutomationConfig(level="auto", require_human_approval=["HIGH"]),
)

_PR_DATA_CONFLICTED = {
    "number": 7,
    "title": "Add feature",
    "body": "",
    "mergeable": False,
    "base": {"sha": "base123"},
    "head": {"sha": "head456"},
}

_PR_DATA_CLEAN = {**_PR_DATA_CONFLICTED, "mergeable": True}

_TRIVIAL_BLOCK = ConflictBlock(
    ours="    return value\n",
    theirs="    return value\n",
)

_LARGE_BLOCK = ConflictBlock(
    ours="\n".join(f"line_ours_{i}" for i in range(20)),
    theirs="\n".join(f"line_theirs_{i}" for i in range(20)),
)

_HIGH_CONF_FILE = ConflictFile(
    path="module.py",
    blocks=[_TRIVIAL_BLOCK],
    resolution_confidence=0.95,
)

_LOW_CONF_FILE = ConflictFile(
    path="complex.py",
    blocks=[_LARGE_BLOCK],
    resolution_confidence=0.4,
)

_HIGH_CONFIDENCE_RESPONSE = json.dumps({
    "resolution": "    return value\n",
    "explanation": "Both sides had identical whitespace-only difference.",
    "confidence": 0.95,
})

_LOW_CONFIDENCE_RESPONSE = json.dumps({
    "resolution": "",
    "explanation": "Cannot determine correct merge without understanding intent.",
    "confidence": 0.5,
})


def _pr_ctx(
    provider: MockProvider,
    conflict_files: list[ConflictFile] | None = None,
    pr_data: dict | None = None,
) -> AgentContext:
    return AgentContext(
        event=_PR_EVENT,
        config=_CONFIG,
        provider=provider,
        pr_data=pr_data if pr_data is not None else _PR_DATA_CONFLICTED,
        diff="--- a/module.py\n+++ b/module.py\n@@ -1 +1 @@\n-old\n+new",
        conflict_files=conflict_files or [],
    )


def _push_ctx(
    provider: MockProvider,
    conflict_files: list[ConflictFile] | None = None,
) -> AgentContext:
    return AgentContext(
        event=_PUSH_EVENT,
        config=_CONFIG,
        provider=provider,
        conflict_files=conflict_files or [],
    )


# ── PR event — output types ───────────────────────────────────────────────────

def test_pr_event_uses_review_comments() -> None:
    provider = MockProvider(default_response=CannedResponse(_HIGH_CONFIDENCE_RESPONSE))
    result = ConflictResolutionAgent().run(_pr_ctx(provider, [_HIGH_CONF_FILE]))
    assert result.review_comments
    assert not result.issue_comments


def test_pr_event_no_post_comment_proposed() -> None:
    provider = MockProvider(default_response=CannedResponse(_HIGH_CONFIDENCE_RESPONSE))
    result = ConflictResolutionAgent().run(_pr_ctx(provider, [_HIGH_CONF_FILE]))
    kinds = {a.kind for a in result.proposed_actions}
    assert ActionKind.POST_COMMENT not in kinds


# ── push event — output types ─────────────────────────────────────────────────

def test_push_event_uses_issue_comments() -> None:
    provider = MockProvider(default_response=CannedResponse(_LOW_CONFIDENCE_RESPONSE))
    result = ConflictResolutionAgent().run(_push_ctx(provider, [_LOW_CONF_FILE]))
    assert result.issue_comments
    assert not result.review_comments


# ── confidence thresholds ─────────────────────────────────────────────────────

def test_high_confidence_proposes_modify_code() -> None:
    provider = MockProvider(default_response=CannedResponse(_HIGH_CONFIDENCE_RESPONSE))
    result = ConflictResolutionAgent().run(_pr_ctx(provider, [_HIGH_CONF_FILE]))
    kinds = {a.kind for a in result.proposed_actions}
    assert ActionKind.MODIFY_CODE in kinds


def test_low_confidence_escalates() -> None:
    provider = MockProvider(default_response=CannedResponse(_LOW_CONFIDENCE_RESPONSE))
    result = ConflictResolutionAgent().run(_pr_ctx(provider, [_LOW_CONF_FILE]))
    assert result.needs_human_review
    kinds = {a.kind for a in result.proposed_actions}
    assert ActionKind.MODIFY_CODE not in kinds


def test_low_confidence_file_level_escalates() -> None:
    """A ConflictFile with low resolution_confidence escalates without LLM call."""
    provider = MockProvider(default_response=CannedResponse(_HIGH_CONFIDENCE_RESPONSE))
    result = ConflictResolutionAgent().run(_pr_ctx(provider, [_LOW_CONF_FILE]))
    assert result.needs_human_review
    # provider should NOT be called for a file already deemed low-confidence
    assert provider.call_count == 0


# ── risk ceiling ─────────────────────────────────────────────────────────────

def test_conflict_resolution_risk_ceiling_is_medium() -> None:
    assert ConflictResolutionAgent.risk_level == RiskLevel.MEDIUM


def test_ceiling_not_violated() -> None:
    provider = MockProvider(default_response=CannedResponse(_HIGH_CONFIDENCE_RESPONSE))
    result = ConflictResolutionAgent().run(_pr_ctx(provider, [_HIGH_CONF_FILE]))
    ConflictResolutionAgent().validate_ceiling(result)


def test_ceiling_not_violated_low_confidence() -> None:
    provider = MockProvider(default_response=CannedResponse(_LOW_CONFIDENCE_RESPONSE))
    result = ConflictResolutionAgent().run(_pr_ctx(provider, [_LOW_CONF_FILE]))
    ConflictResolutionAgent().validate_ceiling(result)


# ── guard rails ───────────────────────────────────────────────────────────────

def test_no_provider_returns_finding() -> None:
    ctx = AgentContext(
        event=_PR_EVENT,
        config=_CONFIG,
        provider=None,
        pr_data=_PR_DATA_CONFLICTED,
        conflict_files=[_HIGH_CONF_FILE],
    )
    result = ConflictResolutionAgent().run(ctx)
    assert result.findings
    assert "No provider" in result.findings[0].summary


def test_clean_pr_returns_early() -> None:
    provider = MockProvider(default_response=CannedResponse(_HIGH_CONFIDENCE_RESPONSE))
    result = ConflictResolutionAgent().run(_pr_ctx(provider, pr_data=_PR_DATA_CLEAN))
    assert result.findings
    assert "cleanly mergeable" in result.findings[0].summary
    assert provider.call_count == 0


def test_no_conflict_files_and_no_diff_returns_early() -> None:
    ctx = AgentContext(
        event=_PR_EVENT,
        config=_CONFIG,
        provider=MockProvider(),
        pr_data=_PR_DATA_CONFLICTED,
        conflict_files=[],
        diff="",
    )
    result = ConflictResolutionAgent().run(ctx)
    assert result.findings


def test_no_conflict_files_with_unmergeable_pr() -> None:
    """Falls back to diff-based analysis when conflict_files is empty."""
    ctx = AgentContext(
        event=_PR_EVENT,
        config=_CONFIG,
        provider=MockProvider(),
        pr_data=_PR_DATA_CONFLICTED,
        conflict_files=[],
        diff="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new",
    )
    result = ConflictResolutionAgent().run(ctx)
    # Fallback path: unmergeable PR → human review comment
    assert result.needs_human_review
    assert result.review_comments


def test_provider_error_returns_escalation() -> None:
    provider = MockProvider(raise_on_complete=RuntimeError("timeout"))
    result = ConflictResolutionAgent().run(_pr_ctx(provider, [_HIGH_CONF_FILE]))
    assert result.needs_human_review


def test_bad_json_treated_as_low_confidence() -> None:
    provider = MockProvider(default_response=CannedResponse("not json"))
    result = ConflictResolutionAgent().run(_pr_ctx(provider, [_HIGH_CONF_FILE]))
    assert result.needs_human_review


def test_handles_events() -> None:
    agent = ConflictResolutionAgent()
    assert "pull_request.opened" in agent.handles_events
    assert "pull_request.synchronize" in agent.handles_events
    assert "push" in agent.handles_events
