"""Tests for repoheart.agents.pr_review."""

from __future__ import annotations

import json

from repoheart.agents.pr_review import PRReviewAgent
from repoheart.config.schema import AutomationConfig, ProviderConfig, RepoHeartConfig
from repoheart.events.types import InternalEvent
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.mock import CannedResponse, MockProvider
from repoheart.safety.policy import ActionKind, RiskLevel

_EVENT = InternalEvent(
    event_name="pull_request",
    action="opened",
    repo_full_name="org/repo",
    payload={"pull_request": {"number": 42}},
    sender_login="dev",
)

_CONFIG = RepoHeartConfig(
    provider=ProviderConfig(name="mock"),
    automation=AutomationConfig(level="auto"),
)

_PR_DATA = {
    "number": 42,
    "title": "Fix null pointer in config loader",
    "body": "Handles the case where config file is missing.",
    "base": {"sha": "abc123"},
    "head": {"sha": "def456"},
}

_DIFF = """\
--- a/repoheart/config/loader.py
+++ b/repoheart/config/loader.py
@@ -10,6 +10,8 @@ def load(path):
+    if path is None:
+        raise ValueError("path must not be None")
     with open(path) as f:
         return yaml.safe_load(f)
"""

_VALID_RESPONSE = json.dumps({
    "comments": [
        {
            "severity": "warning",
            "file": "repoheart/config/loader.py",
            "line": 12,
            "title": "Terse error message",
            "body": "ValueError message could be more descriptive.",
            "suggestion": "Include the expected type in the message.",
        }
    ],
    "overall": "The change looks correct but the error message is terse.",
})

_CLEAN_RESPONSE = json.dumps({
    "comments": [],
    "overall": "No issues found. The diff is clean and well-structured.",
})


def _ctx(provider: MockProvider, diff: str = _DIFF) -> AgentContext:
    return AgentContext(
        event=_EVENT,
        config=_CONFIG,
        provider=provider,
        pr_data=_PR_DATA,
        diff=diff,
        changed_files=["repoheart/config/loader.py"],
    )


def _valid_ctx() -> AgentContext:
    return _ctx(MockProvider(default_response=CannedResponse(_VALID_RESPONSE)))


def test_pr_review_returns_review_comments() -> None:
    result = PRReviewAgent().run(_valid_ctx())
    assert result.review_comments
    rc = result.review_comments[0]
    assert rc.title
    assert rc.severity == "warning"


def test_pr_review_no_proposed_comment_action() -> None:
    """PR review does not self-post; consolidator handles the comment."""
    result = PRReviewAgent().run(_valid_ctx())
    kinds = {a.kind for a in result.proposed_actions}
    assert ActionKind.POST_COMMENT not in kinds


def test_pr_review_risk_ceiling_safe() -> None:
    agent = PRReviewAgent()
    assert agent.risk_level == RiskLevel.SAFE


def test_pr_review_ceiling_not_violated() -> None:
    result = PRReviewAgent().run(_valid_ctx())
    PRReviewAgent().validate_ceiling(result)


def test_pr_review_clean_diff() -> None:
    provider = MockProvider(default_response=CannedResponse(_CLEAN_RESPONSE))
    result = PRReviewAgent().run(_ctx(provider))
    assert not result.review_comments
    assert not result.needs_human_review


def test_pr_review_no_provider() -> None:
    ctx = AgentContext(event=_EVENT, config=_CONFIG, provider=None, pr_data=_PR_DATA, diff=_DIFF)
    result = PRReviewAgent().run(ctx)
    assert result.findings
    assert "No provider" in result.findings[0].summary


def test_pr_review_no_pr_data() -> None:
    ctx = AgentContext(event=_EVENT, config=_CONFIG, provider=MockProvider(), diff=_DIFF)
    result = PRReviewAgent().run(ctx)
    assert result.findings
    assert "No PR data" in result.findings[0].summary


def test_pr_review_empty_diff() -> None:
    result = PRReviewAgent().run(_ctx(MockProvider(), diff=""))
    assert result.findings
    assert "Empty diff" in result.findings[0].summary


def test_pr_review_provider_error() -> None:
    result = PRReviewAgent().run(_ctx(MockProvider(raise_on_complete=RuntimeError("boom"))))
    assert result.findings
    assert "Provider error" in result.findings[0].summary


def test_pr_review_bad_json() -> None:
    provider = MockProvider(default_response=CannedResponse("not json"))
    result = PRReviewAgent().run(_ctx(provider))
    assert result.findings
    assert "JSON parsing failed" in result.findings[0].summary


def test_pr_review_critical_sets_needs_human_review() -> None:
    critical_response = json.dumps({
        "comments": [
            {
                "severity": "critical",
                "file": "foo.py",
                "line": 1,
                "title": "Null deref",
                "body": "Dangerous null dereference.",
                "suggestion": "Add null check.",
            }
        ],
        "overall": "Dangerous bug.",
    })
    provider = MockProvider(default_response=CannedResponse(critical_response))
    result = PRReviewAgent().run(_ctx(provider))
    assert result.needs_human_review


def test_pr_review_handles_events() -> None:
    agent = PRReviewAgent()
    assert "pull_request.opened" in agent.handles_events
    assert "pull_request.synchronize" in agent.handles_events


def test_pr_review_review_comment_has_file_and_line() -> None:
    result = PRReviewAgent().run(_valid_ctx())
    rc = result.review_comments[0]
    assert rc.file == "repoheart/config/loader.py"
    assert rc.line == 12


def test_pr_review_no_findings_in_success_path() -> None:
    result = PRReviewAgent().run(_valid_ctx())
    assert not result.findings
