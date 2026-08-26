"""Tests for repoheart.agents.code_quality."""

from __future__ import annotations

import json

from repoheart.agents.code_quality import CodeQualityAgent
from repoheart.config.schema import AutomationConfig, ProviderConfig, RepoHeartConfig
from repoheart.events.types import InternalEvent
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.mock import CannedResponse, MockProvider
from repoheart.safety.policy import ActionKind, RiskLevel

_EVENT = InternalEvent(
    event_name="pull_request",
    action="opened",
    repo_full_name="org/repo",
    payload={"pull_request": {"number": 7}},
    sender_login="dev",
)

_CONFIG = RepoHeartConfig(
    provider=ProviderConfig(name="mock"),
    automation=AutomationConfig(level="auto"),
)

_LINTER_OUTPUT = "=== ruff ===\nfoo.py:10:1: E501 line too long"

_VALID_RESPONSE = json.dumps({
    "comments": [
        {
            "severity": "warning",
            "tool": "ruff",
            "file": "foo.py",
            "line": 10,
            "title": "Line too long",
            "body": "Line exceeds 100 characters.",
            "suggestion": "Break the line into multiple lines.",
            "category": "style",
        }
    ],
    "overall": "Minor style issues found.",
})

_CLEAN_RESPONSE = json.dumps({
    "comments": [],
    "overall": "No actionable issues found.",
})


def _ctx(
    provider: MockProvider,
    changed_files: list[str] | None = None,
    linter_output: str = _LINTER_OUTPUT,
) -> AgentContext:
    files = changed_files if changed_files is not None else ["foo.py", "bar.py"]
    return AgentContext(
        event=_EVENT,
        config=_CONFIG,
        provider=provider,
        changed_files=files,
        linter_output=linter_output,
    )


def _valid_ctx() -> AgentContext:
    return _ctx(MockProvider(default_response=CannedResponse(_VALID_RESPONSE)))


def test_code_quality_returns_review_comments() -> None:
    result = CodeQualityAgent().run(_valid_ctx())
    assert result.review_comments
    rc = result.review_comments[0]
    assert rc.severity == "warning"
    assert rc.title


def test_code_quality_no_post_comment() -> None:
    result = CodeQualityAgent().run(_valid_ctx())
    kinds = {a.kind for a in result.proposed_actions}
    assert ActionKind.POST_COMMENT not in kinds


def test_code_quality_risk_ceiling_safe() -> None:
    assert CodeQualityAgent().risk_level == RiskLevel.SAFE


def test_code_quality_ceiling_not_violated() -> None:
    result = CodeQualityAgent().run(_valid_ctx())
    CodeQualityAgent().validate_ceiling(result)


def test_code_quality_clean_output() -> None:
    provider = MockProvider(default_response=CannedResponse(_CLEAN_RESPONSE))
    result = CodeQualityAgent().run(_ctx(provider))
    assert not result.review_comments


def test_code_quality_no_provider() -> None:
    ctx = AgentContext(
        event=_EVENT, config=_CONFIG, provider=None, changed_files=["foo.py"],
        linter_output=_LINTER_OUTPUT,
    )
    result = CodeQualityAgent().run(ctx)
    assert "No provider" in result.findings[0].summary


def test_code_quality_no_changed_files() -> None:
    ctx = AgentContext(
        event=_EVENT, config=_CONFIG, provider=MockProvider(),
        changed_files=[],
    )
    result = CodeQualityAgent().run(ctx)
    assert "No changed files" in result.findings[0].summary


def test_code_quality_no_linter_output() -> None:
    ctx = AgentContext(
        event=_EVENT, config=_CONFIG, provider=MockProvider(),
        changed_files=["foo.py"], linter_output="",
    )
    result = CodeQualityAgent().run(ctx)
    assert "No linter output" in result.findings[0].summary


def test_code_quality_no_python_files() -> None:
    ctx = AgentContext(
        event=_EVENT, config=_CONFIG, provider=MockProvider(),
        changed_files=["README.md"], linter_output=_LINTER_OUTPUT,
    )
    result = CodeQualityAgent().run(ctx)
    assert "No Python files" in result.findings[0].summary


def test_code_quality_provider_error() -> None:
    result = CodeQualityAgent().run(
        _ctx(MockProvider(raise_on_complete=RuntimeError("boom")))
    )
    assert "Provider error" in result.findings[0].summary


def test_code_quality_bad_json() -> None:
    result = CodeQualityAgent().run(
        _ctx(MockProvider(default_response=CannedResponse("not json")))
    )
    assert "JSON parsing failed" in result.findings[0].summary


def test_code_quality_review_comment_has_file() -> None:
    result = CodeQualityAgent().run(_valid_ctx())
    rc = result.review_comments[0]
    assert rc.file == "foo.py"
    assert rc.line == 10


def test_code_quality_no_findings_in_success_path() -> None:
    result = CodeQualityAgent().run(_valid_ctx())
    assert not result.findings
