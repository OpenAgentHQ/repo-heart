"""Tests for repoheart.agents.documentation (DocumentationAgent)."""

from __future__ import annotations

import json

from repoheart.agents.documentation import DocumentationAgent, _extract_changed_symbols
from repoheart.config.schema import (
    AgentsConfig,
    DocumentationAgentConfig,
    ProviderConfig,
    RepoHeartConfig,
)
from repoheart.events.types import InternalEvent
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.mock import CannedResponse, MockProvider
from repoheart.safety.policy import RiskLevel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_DIFF = """\
diff --git a/repoheart/utils.py b/repoheart/utils.py
index 000..111 100644
--- a/repoheart/utils.py
+++ b/repoheart/utils.py
@@ -1,3 +1,15 @@
+def parse_labels(raw: list[dict]) -> list[str]:
+    return [item["name"] for item in raw if "name" in item]
+
+class SymbolExtractor:
+    def extract(self, source: str) -> list[str]:
+        return []
"""

_DOC_REVIEW_RESPONSE = json.dumps(
    {
        "comments": [
            {
                "file": "repoheart/utils.py",
                "line": 1,
                "title": "Missing docstring on parse_labels",
                "body": "parse_labels has no docstring.",
                "suggestion": '"""Parse label dicts into name strings."""',
            }
        ]
    }
)

_EMPTY_REVIEW_RESPONSE = json.dumps({"comments": []})

_CHANGELOG_RESPONSE = json.dumps(
    {
        "version": "v1.2.0",
        "date": "2026-08-26",
        "changelog": "### Added\n- New feature X\n\n### Fixed\n- Bug Y",
    }
)


def _make_event(name: str, action: str = "", payload: dict | None = None) -> InternalEvent:
    return InternalEvent(
        event_name=name,
        action=action,
        repo_full_name="org/repo",
        payload=payload or {},
        sender_login="bot",
    )


def _make_config(changelog_on_release: bool = True) -> RepoHeartConfig:
    return RepoHeartConfig(
        provider=ProviderConfig(name="opencode", model="test-model"),
        agents=AgentsConfig(
            documentation=True,
            documentation_config=DocumentationAgentConfig(
                enabled=True,
                changelog_on_release=changelog_on_release,
            ),
        ),
    )


def _make_context(
    event: InternalEvent,
    provider: MockProvider,
    diff: str = "",
    config: RepoHeartConfig | None = None,
) -> AgentContext:
    return AgentContext(
        event=event,
        config=config or _make_config(),
        provider=provider,
        diff=diff,
    )


# ---------------------------------------------------------------------------
# _extract_changed_symbols unit tests
# ---------------------------------------------------------------------------


def test_extract_symbols_finds_public_def_and_class() -> None:
    symbols = _extract_changed_symbols(_SAMPLE_DIFF)
    assert "repoheart/utils.py" in symbols
    names = [name for name, _ in symbols["repoheart/utils.py"]]
    assert "parse_labels" in names
    assert "SymbolExtractor" in names


def test_extract_symbols_ignores_private() -> None:
    diff = (
        "+++ b/foo.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+def _private_helper():\n"
        "+    pass\n"
    )
    symbols = _extract_changed_symbols(diff)
    assert not symbols  # private names filtered out


def test_extract_symbols_ignores_non_python_files() -> None:
    diff = (
        "+++ b/repoheart/style.css\n"
        "@@ -0,0 +1 @@\n"
        "+def notpython() {}\n"
    )
    symbols = _extract_changed_symbols(diff)
    assert not symbols


# ---------------------------------------------------------------------------
# PR mode
# ---------------------------------------------------------------------------


def test_pr_mode_returns_review_comments() -> None:
    provider = MockProvider(default_response=CannedResponse(_DOC_REVIEW_RESPONSE))
    event = _make_event("pull_request", "opened")
    ctx = _make_context(event, provider, diff=_SAMPLE_DIFF)

    agent = DocumentationAgent()
    result = agent.run(ctx)

    assert provider.call_count == 1
    assert len(result.review_comments) == 1
    assert result.issue_comments == []
    rc = result.review_comments[0]
    assert rc.category == "docs"
    assert rc.severity == "info"
    assert "parse_labels" in rc.title
    assert rc.file == "repoheart/utils.py"


def test_pr_mode_empty_diff_returns_finding() -> None:
    provider = MockProvider(default_response=CannedResponse(_EMPTY_REVIEW_RESPONSE))
    event = _make_event("pull_request", "opened")
    ctx = _make_context(event, provider, diff="")

    result = DocumentationAgent().run(ctx)

    assert provider.call_count == 0
    assert result.review_comments == []
    assert len(result.findings) == 1


def test_pr_mode_no_public_symbols_returns_finding() -> None:
    diff_private_only = (
        "+++ b/foo.py\n"
        "@@ -0,0 +1 @@\n"
        "+def _hidden():\n"
        "+    pass\n"
    )
    provider = MockProvider(default_response=CannedResponse(_EMPTY_REVIEW_RESPONSE))
    event = _make_event("pull_request", "synchronize")
    ctx = _make_context(event, provider, diff=diff_private_only)

    result = DocumentationAgent().run(ctx)

    assert provider.call_count == 0
    assert result.review_comments == []
    assert len(result.findings) == 1


def test_pr_mode_empty_llm_comments_returns_no_review_comments() -> None:
    provider = MockProvider(default_response=CannedResponse(_EMPTY_REVIEW_RESPONSE))
    event = _make_event("pull_request", "opened")
    ctx = _make_context(event, provider, diff=_SAMPLE_DIFF)

    result = DocumentationAgent().run(ctx)

    assert provider.call_count == 1
    assert result.review_comments == []
    assert result.findings == []


def test_pr_mode_provider_error_returns_finding() -> None:
    from repoheart.providers.base import ProviderError

    provider = MockProvider(raise_on_complete=ProviderError)
    event = _make_event("pull_request", "opened")
    ctx = _make_context(event, provider, diff=_SAMPLE_DIFF)

    result = DocumentationAgent().run(ctx)

    assert result.review_comments == []
    assert any("Provider error" in f.summary for f in result.findings)


def test_pr_mode_bad_json_returns_finding() -> None:
    provider = MockProvider(default_response=CannedResponse("not-json{{"))
    event = _make_event("pull_request", "opened")
    ctx = _make_context(event, provider, diff=_SAMPLE_DIFF)

    result = DocumentationAgent().run(ctx)

    assert result.review_comments == []
    assert any("parsing failed" in f.summary for f in result.findings)


# ---------------------------------------------------------------------------
# Push mode (issue_comments instead of review_comments)
# ---------------------------------------------------------------------------


def test_push_mode_returns_issue_comments() -> None:
    provider = MockProvider(default_response=CannedResponse(_DOC_REVIEW_RESPONSE))
    event = _make_event("push")
    ctx = _make_context(event, provider, diff=_SAMPLE_DIFF)

    result = DocumentationAgent().run(ctx)

    assert provider.call_count == 1
    assert result.review_comments == []
    assert len(result.issue_comments) == 1
    ic = result.issue_comments[0]
    assert ic.severity == "info"
    assert "parse_labels" in ic.title


# ---------------------------------------------------------------------------
# Release / changelog mode
# ---------------------------------------------------------------------------


def test_release_mode_returns_issue_comment_with_changelog() -> None:
    provider = MockProvider(default_response=CannedResponse(_CHANGELOG_RESPONSE))
    payload = {
        "release": {
            "tag_name": "v1.2.0",
            "name": "v1.2.0",
            "body": "",
            "published_at": "2026-08-26T00:00:00Z",
        }
    }
    event = _make_event("release", "published", payload=payload)
    ctx = _make_context(event, provider)

    result = DocumentationAgent().run(ctx)

    assert provider.call_count == 1
    assert result.review_comments == []
    assert len(result.issue_comments) == 1
    ic = result.issue_comments[0]
    assert "v1.2.0" in ic.title
    assert "### Added" in ic.body


def test_release_mode_missing_tag_returns_finding() -> None:
    provider = MockProvider(default_response=CannedResponse(_CHANGELOG_RESPONSE))
    event = _make_event("release", "published", payload={"release": {}})
    ctx = _make_context(event, provider)

    result = DocumentationAgent().run(ctx)

    assert provider.call_count == 0
    assert any("tag_name" in f.summary for f in result.findings)


def test_release_mode_changelog_disabled_returns_finding() -> None:
    provider = MockProvider(default_response=CannedResponse(_CHANGELOG_RESPONSE))
    payload = {
        "release": {
            "tag_name": "v1.2.0",
            "name": "v1.2.0",
            "body": "",
            "published_at": "2026-08-26T00:00:00Z",
        }
    }
    event = _make_event("release", "published", payload=payload)
    ctx = _make_context(event, provider, config=_make_config(changelog_on_release=False))

    result = DocumentationAgent().run(ctx)

    assert provider.call_count == 0
    assert result.issue_comments == []
    assert any("disabled" in f.summary for f in result.findings)


def test_release_mode_provider_error_returns_finding() -> None:
    from repoheart.providers.base import ProviderError

    provider = MockProvider(raise_on_complete=ProviderError)
    payload = {
        "release": {
            "tag_name": "v1.0.0",
            "name": "v1.0.0",
            "body": "",
            "published_at": "2026-08-26T00:00:00Z",
        }
    }
    event = _make_event("release", "published", payload=payload)
    ctx = _make_context(event, provider)

    result = DocumentationAgent().run(ctx)

    assert result.issue_comments == []
    assert any("Provider error" in f.summary for f in result.findings)


# ---------------------------------------------------------------------------
# No provider
# ---------------------------------------------------------------------------


def test_no_provider_returns_finding() -> None:
    event = _make_event("pull_request", "opened")
    ctx = AgentContext(
        event=event,
        config=_make_config(),
        provider=None,
        diff=_SAMPLE_DIFF,
    )

    result = DocumentationAgent().run(ctx)

    assert result.review_comments == []
    assert result.issue_comments == []
    assert len(result.findings) == 1


# ---------------------------------------------------------------------------
# Risk ceiling invariant
# ---------------------------------------------------------------------------


def test_risk_ceiling_never_exceeded() -> None:
    provider = MockProvider(default_response=CannedResponse(_DOC_REVIEW_RESPONSE))
    event = _make_event("pull_request", "opened")
    ctx = _make_context(event, provider, diff=_SAMPLE_DIFF)

    agent = DocumentationAgent()
    result = agent.run(ctx)

    assert agent.risk_level == RiskLevel.SAFE
    # validate_ceiling must not raise
    agent.validate_ceiling(result)
    for action in result.proposed_actions:
        assert action.risk is not None
        assert action.risk <= RiskLevel.SAFE


# ---------------------------------------------------------------------------
# Agent metadata
# ---------------------------------------------------------------------------


def test_agent_handles_correct_events() -> None:
    agent = DocumentationAgent()
    assert "pull_request.opened" in agent.handles_events
    assert "push" in agent.handles_events
    assert "release.published" in agent.handles_events


def test_agent_name_matches_registry_key() -> None:
    from repoheart.agents.registry import AGENT_REGISTRY

    assert AGENT_REGISTRY["documentation"] is DocumentationAgent
