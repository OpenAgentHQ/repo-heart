"""PRFlowConsolidator — merges ReviewComment objects from all PR agents.

PR agents return ReviewComment objects (no POST_COMMENT proposals). The
orchestrator collects their AgentResults and calls this consolidator to
produce a single structured review body plus inline comment dicts for the
GitHub PR Review API.
"""

from __future__ import annotations

from repoheart.agents.base import AgentResult, ReviewComment

# Idempotency anchor embedded in the consolidated review body.
CONSOLIDATION_MARKER = "<!-- repoheart:pr-review -->"

_SECTION_TITLES: dict[str, str] = {
    "pr_review": "Code Review",
    "code_quality": "Code Quality",
    "security": "Security",
    "test": "Test Coverage",
}

_SEVERITY_ICONS: dict[str, str] = {
    "critical": "🔴",
    "high": "🟠",
    "warning": "🟡",
    "info": "🔵",
}


def format_review_comment_body(rc: ReviewComment) -> str:
    """Format a ReviewComment into inline GitHub review comment markdown."""
    icon = _SEVERITY_ICONS.get(rc.severity, "•")
    lines = [f"{icon} **{rc.title}** `[{rc.severity}]`", "", rc.body]
    if rc.suggestion:
        lines.extend(["", f"> 💡 {rc.suggestion}"])
    return "\n".join(lines)


def consolidate(
    agent_results: dict[str, AgentResult],
) -> tuple[str, list[dict[str, object]]]:
    """Build (review_body, inline_comments) from all PR agent results.

    review_body:      Markdown for the review-level comment (file-less findings + summaries).
    inline_comments:  List of {path, line, body} for GitHub's review API.
    """
    sections: list[str] = []
    inline_comments: list[dict[str, object]] = []

    for agent_name, section_title in _SECTION_TITLES.items():
        result = agent_results.get(agent_name)
        if result is None:
            continue

        lines: list[str] = [f"### {section_title}"]

        file_less: list[ReviewComment] = []
        for rc in result.review_comments:
            if rc.file and rc.line:
                inline_comments.append({
                    "path": rc.file,
                    "line": rc.line,
                    "body": format_review_comment_body(rc),
                })
            else:
                file_less.append(rc)

        if not file_less and not result.review_comments:
            if result.explanation:
                lines.append(result.explanation)
            else:
                lines.append("_No issues found._")
        else:
            if not file_less and result.review_comments:
                # All comments are inline; show count + summary
                count = len(result.review_comments)
                lines.append(f"_{count} inline comment(s) posted on the diff._")
                if result.explanation:
                    lines.append(f"\n{result.explanation}")
            else:
                for rc in file_less:
                    icon = _SEVERITY_ICONS.get(rc.severity, "•")
                    lines.append(f"- {icon} **{rc.title}** `[{rc.severity}]`")
                    if rc.body:
                        lines.append(f"  {rc.body}")
                    if rc.suggestion:
                        lines.append(f"  > 💡 {rc.suggestion}")
                if result.explanation:
                    lines.append(f"\n{result.explanation}")

        if result.needs_human_review:
            lines.append("\n> ⚠️ **Human review recommended.**")

        sections.append("\n".join(lines))

    if not sections:
        return (
            f"{CONSOLIDATION_MARKER}\n"
            "## RepoHeart PR Review\n\n"
            "_No findings from any PR agent._\n\n"
            "_Automated review by [RepoHeart](https://github.com/OpenAgentHQ/repo-heart)._",
            [],
        )

    body = "\n\n".join(sections)
    review_body = (
        f"{CONSOLIDATION_MARKER}\n"
        "## RepoHeart PR Review\n\n"
        f"{body}\n\n"
        "---\n"
        "_Automated review by [RepoHeart](https://github.com/OpenAgentHQ/repo-heart)._"
    )
    return review_body, inline_comments


def already_reviewed(comments: list[dict[str, object]]) -> bool:
    """Return True if a consolidated review comment already exists on this PR."""
    for comment in comments:
        body = comment.get("body", "") or ""
        if CONSOLIDATION_MARKER in str(body):
            return True
    return False
