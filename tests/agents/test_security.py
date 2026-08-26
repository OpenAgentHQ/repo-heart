"""Tests for repoheart.agents.security."""

from __future__ import annotations

import json

from repoheart.agents.security import SecurityAgent
from repoheart.config.schema import AutomationConfig, ProviderConfig, RepoHeartConfig
from repoheart.events.types import InternalEvent
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.mock import CannedResponse, MockProvider
from repoheart.safety.policy import ActionKind, RiskLevel

_EVENT = InternalEvent(
    event_name="pull_request",
    action="opened",
    repo_full_name="org/repo",
    payload={"pull_request": {"number": 99}},
    sender_login="dev",
)

_CONFIG = RepoHeartConfig(
    provider=ProviderConfig(name="mock"),
    automation=AutomationConfig(level="auto"),
)

_PR_DATA = {
    "number": 99,
    "title": "Add API integration",
    "body": "Wires up the external payment API.",
    "base": {"sha": "aaa"},
    "head": {"sha": "bbb"},
}

_DIFF_WITH_SECRET = """\
+API_KEY = "sk-abc123supersecret"
+PASSWORD = "hunter2"
"""

_DIFF_CLEAN = """\
+def add(a, b):
+    return a + b
"""

_SECRET_RESPONSE = json.dumps({
    "comments": [
        {
            "severity": "critical",
            "category": "hardcoded_secret",
            "file": "config.py",
            "line": 1,
            "title": "Hardcoded API key detected",
            "body": "An API key is hardcoded in the source.",
            "suggestion": "Move to an environment variable.",
        }
    ],
    "has_secrets": True,
    "overall": "Critical: hardcoded secret found in config.py.",
})

_CLEAN_RESPONSE = json.dumps({
    "comments": [],
    "has_secrets": False,
    "overall": "No security issues detected.",
})

_HIGH_RESPONSE = json.dumps({
    "comments": [
        {
            "severity": "high",
            "category": "injection",
            "file": "api.py",
            "line": 5,
            "title": "User input passed to eval()",
            "body": "eval() on untrusted input is dangerous.",
            "suggestion": "Never eval untrusted input.",
        }
    ],
    "has_secrets": False,
    "overall": "High severity injection vulnerability.",
})


def _ctx(
    provider: MockProvider,
    diff: str = _DIFF_WITH_SECRET,
) -> AgentContext:
    return AgentContext(
        event=_EVENT,
        config=_CONFIG,
        provider=provider,
        pr_data=_PR_DATA,
        diff=diff,
        changed_files=["config.py"],
    )


def _secret_ctx() -> AgentContext:
    return _ctx(MockProvider(default_response=CannedResponse(_SECRET_RESPONSE)))


def test_security_finds_secret_and_labels() -> None:
    result = SecurityAgent().run(_secret_ctx())
    kinds = {a.kind for a in result.proposed_actions}
    assert ActionKind.ADD_LABEL in kinds
    label_action = next(a for a in result.proposed_actions if a.kind == ActionKind.ADD_LABEL)
    assert "security-review" in label_action.payload["labels"]


def test_security_sets_needs_human_review_on_secret() -> None:
    result = SecurityAgent().run(_secret_ctx())
    assert result.needs_human_review


def test_security_risk_ceiling_safe() -> None:
    assert SecurityAgent().risk_level == RiskLevel.SAFE


def test_security_ceiling_not_violated() -> None:
    result = SecurityAgent().run(_secret_ctx())
    SecurityAgent().validate_ceiling(result)


def test_security_clean_diff_no_label() -> None:
    provider = MockProvider(default_response=CannedResponse(_CLEAN_RESPONSE))
    result = SecurityAgent().run(_ctx(provider, diff=_DIFF_CLEAN))
    kinds = {a.kind for a in result.proposed_actions}
    assert ActionKind.ADD_LABEL not in kinds
    assert not result.needs_human_review


def test_security_high_severity_triggers_label() -> None:
    provider = MockProvider(default_response=CannedResponse(_HIGH_RESPONSE))
    result = SecurityAgent().run(_ctx(provider))
    kinds = {a.kind for a in result.proposed_actions}
    assert ActionKind.ADD_LABEL in kinds


def test_security_no_provider() -> None:
    ctx = AgentContext(
        event=_EVENT, config=_CONFIG, provider=None,
        pr_data=_PR_DATA, diff=_DIFF_WITH_SECRET,
    )
    result = SecurityAgent().run(ctx)
    assert "No provider" in result.findings[0].summary


def test_security_no_pr_data() -> None:
    ctx = AgentContext(
        event=_EVENT, config=_CONFIG, provider=MockProvider(),
        diff=_DIFF_WITH_SECRET,
    )
    result = SecurityAgent().run(ctx)
    assert "No PR data" in result.findings[0].summary


def test_security_empty_diff() -> None:
    result = SecurityAgent().run(_ctx(MockProvider(), diff=""))
    assert "Empty diff" in result.findings[0].summary


def test_security_provider_error() -> None:
    result = SecurityAgent().run(_ctx(MockProvider(raise_on_complete=RuntimeError("boom"))))
    assert "Provider error" in result.findings[0].summary


def test_security_bad_json() -> None:
    provider = MockProvider(default_response=CannedResponse("nope"))
    result = SecurityAgent().run(_ctx(provider))
    assert "JSON parsing failed" in result.findings[0].summary


def test_security_no_post_comment() -> None:
    result = SecurityAgent().run(_secret_ctx())
    kinds = {a.kind for a in result.proposed_actions}
    assert ActionKind.POST_COMMENT not in kinds


def test_security_returns_review_comments() -> None:
    result = SecurityAgent().run(_secret_ctx())
    assert result.review_comments
    rc = result.review_comments[0]
    assert rc.severity == "critical"
    assert rc.file == "config.py"
