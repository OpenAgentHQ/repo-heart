"""Tests for repoheart.orchestrator.issue_flow."""

from __future__ import annotations

from repoheart.agents.base import IssueComment
from repoheart.orchestrator.issue_flow import (
    ISSUE_AGENT_MARKERS,
    comment_already_posted,
    format_issue_comment,
)


def _ic(
    title: str = "Test",
    body: str = "Body text.",
    severity: str = "info",
    references: list[str] | None = None,
) -> IssueComment:
    return IssueComment(title=title, body=body, severity=severity, references=references or [])


# ── format_issue_comment() ────────────────────────────────────────────────────

def test_format_contains_marker_for_triage() -> None:
    text = format_issue_comment(_ic("Issue Triage"), "issue_triage")
    assert ISSUE_AGENT_MARKERS["issue_triage"] in text


def test_format_contains_marker_for_duplicate() -> None:
    text = format_issue_comment(_ic("Possible duplicate"), "duplicate_detection")
    assert ISSUE_AGENT_MARKERS["duplicate_detection"] in text


def test_format_contains_marker_for_resolution() -> None:
    text = format_issue_comment(_ic("Possibly already fixed"), "issue_resolution")
    assert ISSUE_AGENT_MARKERS["issue_resolution"] in text


def test_format_contains_title() -> None:
    text = format_issue_comment(_ic("My Title"), "issue_triage")
    assert "My Title" in text


def test_format_contains_body() -> None:
    text = format_issue_comment(_ic(body="Detailed body here."), "issue_triage")
    assert "Detailed body here." in text


def test_format_contains_severity_badge() -> None:
    text = format_issue_comment(_ic(severity="critical"), "issue_triage")
    assert "Critical" in text or "🔴" in text


def test_format_contains_references() -> None:
    text = format_issue_comment(_ic(references=["#42", "#99"]), "duplicate_detection")
    assert "#42" in text
    assert "#99" in text


def test_format_unknown_agent_uses_fallback_marker() -> None:
    text = format_issue_comment(_ic(), "some_custom_agent")
    assert "<!-- repoheart:some_custom_agent -->" in text


def test_format_contains_repoheart_attribution() -> None:
    text = format_issue_comment(_ic(), "issue_triage")
    assert "RepoHeart" in text


def test_format_info_severity_badge() -> None:
    text = format_issue_comment(_ic(severity="info"), "issue_triage")
    assert "Info" in text or "🔵" in text


# ── comment_already_posted() ─────────────────────────────────────────────────

def test_comment_already_posted_false_on_empty() -> None:
    assert not comment_already_posted([], "issue_triage")


def test_comment_already_posted_false_on_unrelated() -> None:
    comments = [{"body": "LGTM"}, {"body": "<!-- repoheart:pr-review -->stuff"}]
    assert not comment_already_posted(comments, "issue_triage")


def test_comment_already_posted_true_when_marker_present() -> None:
    marker = ISSUE_AGENT_MARKERS["issue_triage"]
    comments = [{"body": f"{marker}\n**Issue Triage** 🔵\n\nBody."}]
    assert comment_already_posted(comments, "issue_triage")


def test_comment_already_posted_handles_none_body() -> None:
    marker = ISSUE_AGENT_MARKERS["duplicate_detection"]
    comments = [{"body": None}, {"body": f"{marker}\ncontent"}]
    assert comment_already_posted(comments, "duplicate_detection")


def test_each_agent_has_unique_marker() -> None:
    markers = list(ISSUE_AGENT_MARKERS.values())
    assert len(markers) == len(set(markers))


def test_comment_not_posted_wrong_agent() -> None:
    marker = ISSUE_AGENT_MARKERS["issue_triage"]
    comments = [{"body": f"{marker}\nTriage done."}]
    # The resolution-check marker is different — should return False
    assert not comment_already_posted(comments, "issue_resolution")
