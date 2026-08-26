"""Tests for repoheart.agents.test_agent."""

from __future__ import annotations

import json

from repoheart.agents.test_agent import TestCoverageAgent
from repoheart.config.schema import AutomationConfig, ProviderConfig, RepoHeartConfig
from repoheart.events.types import InternalEvent
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.mock import CannedResponse, MockProvider
from repoheart.safety.policy import ActionKind, RiskLevel

_EVENT = InternalEvent(
    event_name="pull_request",
    action="opened",
    repo_full_name="org/repo",
    payload={"pull_request": {"number": 55}},
    sender_login="dev",
)

_CONFIG = RepoHeartConfig(
    provider=ProviderConfig(name="mock"),
    automation=AutomationConfig(level="auto"),
)

_CHANGED_FILES = ["repoheart/config/loader.py", "repoheart/agents/base.py"]

_TEST_MAPPING = {
    "repoheart/config/loader.py": ["tests/test_config_loader.py"],
    "repoheart/agents/base.py": [],
}

_GOOD_RESPONSE = json.dumps({
    "comments": [],
    "coverage_assessment": "good",
    "overall": "All changed modules have corresponding tests.",
})

_POOR_RESPONSE = json.dumps({
    "comments": [
        {
            "severity": "warning",
            "file": "repoheart/agents/base.py",
            "line": None,
            "title": "No tests for base.py changes",
            "body": "No test file found for the changes in base.py.",
            "suggestion": "Add tests covering the new method added to Agent.",
        }
    ],
    "coverage_assessment": "poor",
    "overall": "base.py has no corresponding test file.",
})


def _ctx(
    provider: MockProvider,
    changed_files: list[str] | None = None,
    test_mapping: dict | None = None,
    diff: str = "",
) -> AgentContext:
    return AgentContext(
        event=_EVENT,
        config=_CONFIG,
        provider=provider,
        changed_files=changed_files or _CHANGED_FILES,
        test_mapping=test_mapping or _TEST_MAPPING,
        diff=diff,
    )


def _good_ctx() -> AgentContext:
    return _ctx(MockProvider(default_response=CannedResponse(_GOOD_RESPONSE)))


def _poor_ctx() -> AgentContext:
    return _ctx(MockProvider(default_response=CannedResponse(_POOR_RESPONSE)))


def test_test_agent_good_coverage() -> None:
    result = TestCoverageAgent().run(_good_ctx())
    assert not result.review_comments
    assert not result.needs_human_review


def test_test_agent_poor_coverage_needs_review() -> None:
    result = TestCoverageAgent().run(_poor_ctx())
    assert result.needs_human_review


def test_test_agent_review_comments_populated() -> None:
    result = TestCoverageAgent().run(_poor_ctx())
    assert result.review_comments
    rc = result.review_comments[0]
    assert rc.severity == "warning"
    assert rc.category == "coverage"


def test_test_agent_risk_ceiling_safe() -> None:
    assert TestCoverageAgent().risk_level == RiskLevel.SAFE


def test_test_agent_ceiling_not_violated() -> None:
    result = TestCoverageAgent().run(_good_ctx())
    TestCoverageAgent().validate_ceiling(result)


def test_test_agent_no_post_comment() -> None:
    result = TestCoverageAgent().run(_good_ctx())
    kinds = {a.kind for a in result.proposed_actions}
    assert ActionKind.POST_COMMENT not in kinds


def test_test_agent_no_provider() -> None:
    ctx = AgentContext(event=_EVENT, config=_CONFIG, provider=None, changed_files=_CHANGED_FILES)
    result = TestCoverageAgent().run(ctx)
    assert "No provider" in result.findings[0].summary


def test_test_agent_no_changed_files() -> None:
    ctx = AgentContext(event=_EVENT, config=_CONFIG, provider=MockProvider())
    result = TestCoverageAgent().run(ctx)
    assert "No changed files" in result.findings[0].summary


def test_test_agent_no_python_files() -> None:
    ctx = AgentContext(
        event=_EVENT, config=_CONFIG, provider=MockProvider(),
        changed_files=["README.md", ".github/workflows/ci.yml"],
    )
    result = TestCoverageAgent().run(ctx)
    assert "No Python files" in result.findings[0].summary


def test_test_agent_provider_error() -> None:
    result = TestCoverageAgent().run(
        _ctx(MockProvider(raise_on_complete=RuntimeError("fail")))
    )
    assert "Provider error" in result.findings[0].summary


def test_test_agent_bad_json() -> None:
    result = TestCoverageAgent().run(
        _ctx(MockProvider(default_response=CannedResponse("{{invalid")))
    )
    assert "JSON parsing failed" in result.findings[0].summary


def test_test_mapping_shown_in_context() -> None:
    """Modules with tests are mapped correctly; missing tests surface in mapping."""
    mapping = _TEST_MAPPING
    assert mapping["repoheart/config/loader.py"] == ["tests/test_config_loader.py"]
    assert mapping["repoheart/agents/base.py"] == []
