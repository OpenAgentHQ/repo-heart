"""Tests for repoheart.orchestrator.pr_flow and the orchestrator PR helpers."""

from __future__ import annotations

import os
import tempfile

from repoheart.agents.base import AgentResult, ReviewComment
from repoheart.orchestrator.pr_flow import (
    CONSOLIDATION_MARKER,
    already_reviewed,
    consolidate,
    format_review_comment_body,
)


def _rc(
    title: str = "Issue",
    body: str = "detail",
    severity: str = "warning",
    file: str | None = None,
    line: int | None = None,
    suggestion: str | None = None,
    category: str | None = None,
) -> ReviewComment:
    return ReviewComment(
        title=title,
        body=body,
        severity=severity,
        file=file,
        line=line,
        suggestion=suggestion,
        category=category,
    )


def _result(
    *review_comments: ReviewComment,
    explanation: str = "",
    needs_human_review: bool = False,
) -> AgentResult:
    return AgentResult(
        review_comments=list(review_comments),
        explanation=explanation,
        needs_human_review=needs_human_review,
    )


# ── consolidate() ─────────────────────────────────────────────────────────────

def test_consolidate_returns_tuple() -> None:
    body, inline = consolidate({"pr_review": _result(_rc())})
    assert isinstance(body, str)
    assert isinstance(inline, list)


def test_consolidate_contains_marker() -> None:
    body, _ = consolidate({"pr_review": _result(_rc("All good."))})
    assert CONSOLIDATION_MARKER in body


def test_consolidate_contains_section_headers() -> None:
    body, _ = consolidate({
        "pr_review": _result(_rc("Terse error message")),
        "security": _result(_rc("API key", severity="critical")),
    })
    assert "### Code Review" in body
    assert "### Security" in body


def test_consolidate_omits_missing_agents() -> None:
    body, _ = consolidate({"pr_review": _result(_rc("Fine."))})
    assert "### Code Quality" not in body
    assert "### Test Coverage" not in body


def test_consolidate_empty_result_shows_no_issues() -> None:
    body, inline = consolidate({"code_quality": AgentResult()})
    assert "_No issues found._" in body
    assert inline == []


def test_consolidate_empty_dict() -> None:
    body, inline = consolidate({})
    assert CONSOLIDATION_MARKER in body
    assert "No findings" in body
    assert inline == []


def test_consolidate_human_review_warning_present() -> None:
    body, _ = consolidate({"security": _result(_rc(severity="critical"), needs_human_review=True)})
    assert "Human review recommended" in body


def test_consolidate_no_human_review_warning_when_clean() -> None:
    body, _ = consolidate({"pr_review": _result(_rc("LGTM"), needs_human_review=False)})
    assert "Human review recommended" not in body


def test_consolidate_includes_explanation() -> None:
    body, _ = consolidate({"pr_review": AgentResult(explanation="Overall the diff is safe.")})
    assert "Overall the diff is safe." in body


def test_consolidate_inline_comment_when_file_and_line_present() -> None:
    rc = _rc("Type error", file="src/foo.py", line=42)
    _, inline = consolidate({"pr_review": _result(rc)})
    assert len(inline) == 1
    assert inline[0]["path"] == "src/foo.py"
    assert inline[0]["line"] == 42


def test_consolidate_file_less_comment_goes_to_body() -> None:
    rc = _rc("Module coverage", file=None, line=None)
    body, inline = consolidate({"test": _result(rc)})
    assert inline == []
    assert "Module coverage" in body


def test_consolidate_all_four_agents() -> None:
    results = {
        "pr_review": _result(_rc("Null deref", severity="critical")),
        "code_quality": _result(_rc("Unused var")),
        "security": _result(_rc("eval() call", severity="high")),
        "test": _result(_rc("No tests for foo.py")),
    }
    body, _ = consolidate(results)
    assert "### Code Review" in body
    assert "### Code Quality" in body
    assert "### Security" in body
    assert "### Test Coverage" in body


def test_consolidate_multiple_inline_comments() -> None:
    rcs = [
        _rc("Bug A", file="a.py", line=1),
        _rc("Bug B", file="b.py", line=2),
    ]
    _, inline = consolidate({"pr_review": _result(*rcs)})
    assert len(inline) == 2
    paths = {c["path"] for c in inline}
    assert paths == {"a.py", "b.py"}


# ── format_review_comment_body() ─────────────────────────────────────────────

def test_format_review_comment_body_contains_title() -> None:
    rc = _rc("Null dereference", body="Variable may be None.", severity="critical")
    text = format_review_comment_body(rc)
    assert "Null dereference" in text
    assert "critical" in text


def test_format_review_comment_body_includes_suggestion() -> None:
    rc = _rc("Null deref", suggestion="Add a None check.")
    text = format_review_comment_body(rc)
    assert "Add a None check." in text


def test_format_review_comment_body_no_suggestion() -> None:
    rc = _rc("LGTM", severity="info")
    text = format_review_comment_body(rc)
    assert "💡" not in text


# ── already_reviewed() ────────────────────────────────────────────────────────

def test_already_reviewed_false_on_empty() -> None:
    assert not already_reviewed([])


def test_already_reviewed_false_on_unrelated_comments() -> None:
    comments = [{"body": "LGTM"}, {"body": "<!-- repoheart:triage -->\nTriage done."}]
    assert not already_reviewed(comments)


def test_already_reviewed_true_when_marker_present() -> None:
    comments = [{"body": f"{CONSOLIDATION_MARKER}\n## RepoHeart PR Review\n..."}]
    assert already_reviewed(comments)


def test_already_reviewed_handles_none_body() -> None:
    comments = [{"body": None}, {"body": f"{CONSOLIDATION_MARKER}\ncontent"}]
    assert already_reviewed(comments)


# ── _filter_to_diff helper ────────────────────────────────────────────────────

def test_filter_to_diff_keeps_matching_files() -> None:
    from repoheart.orchestrator.orchestrator import _filter_to_diff

    diff = "+++ b/src/foo.py\n@@ -1,1 +1,2 @@\n+x = 1"
    inline = [{"path": "src/foo.py", "line": 1, "body": "issue"}]
    result = _filter_to_diff(inline, diff)
    assert result == inline


def test_filter_to_diff_removes_absent_files() -> None:
    from repoheart.orchestrator.orchestrator import _filter_to_diff

    diff = "+++ b/src/foo.py\n@@ -1,1 +1,2 @@\n+x = 1"
    inline = [
        {"path": "src/foo.py", "line": 1, "body": "ok"},
        {"path": "src/bar.py", "line": 2, "body": "not in diff"},
    ]
    result = _filter_to_diff(inline, diff)
    assert len(result) == 1
    assert result[0]["path"] == "src/foo.py"


def test_filter_to_diff_empty_diff_removes_all() -> None:
    from repoheart.orchestrator.orchestrator import _filter_to_diff

    inline = [{"path": "src/foo.py", "line": 1, "body": "x"}]
    result = _filter_to_diff(inline, "")
    assert result == []


# ── _run_linters / _scan_secrets / _map_tests ─────────────────────────────────

def test_run_linters_returns_string() -> None:
    from repoheart.orchestrator.orchestrator import _run_linters

    result = _run_linters(["__nonexistent_file__.py"])
    assert isinstance(result, str)


def test_scan_secrets_returns_string() -> None:
    from repoheart.orchestrator.orchestrator import _scan_secrets

    result = _scan_secrets("diff content")
    assert isinstance(result, str)


def test_map_tests_returns_dict() -> None:
    from repoheart.orchestrator.orchestrator import _map_tests

    with tempfile.TemporaryDirectory() as root:
        tests_dir = os.path.join(root, "tests")
        os.makedirs(tests_dir)
        test_file = os.path.join(tests_dir, "test_foo.py")
        open(test_file, "w").close()  # noqa: WPS515

        mapping = _map_tests(["src/foo.py"], root)
        assert "src/foo.py" in mapping
        found = mapping["src/foo.py"]
        assert any("test_foo.py" in f for f in found)


def test_map_tests_missing_test_returns_empty_list() -> None:
    from repoheart.orchestrator.orchestrator import _map_tests

    with tempfile.TemporaryDirectory() as root:
        mapping = _map_tests(["src/orphan.py"], root)
        assert mapping["src/orphan.py"] == []


def test_map_tests_ignores_non_python() -> None:
    from repoheart.orchestrator.orchestrator import _map_tests

    with tempfile.TemporaryDirectory() as root:
        mapping = _map_tests(["README.md", "src/bar.py"], root)
        assert "README.md" not in mapping
        assert "src/bar.py" in mapping
