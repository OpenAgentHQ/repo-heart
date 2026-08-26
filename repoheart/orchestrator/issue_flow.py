"""Issue comment formatting and idempotency helpers for issue agents.

Issue agents produce IssueComment objects; this module formats them into
GitHub comment bodies and checks whether they have already been posted.
"""

from __future__ import annotations

from repoheart.agents.base import IssueComment

ISSUE_AGENT_MARKERS: dict[str, str] = {
    "issue_triage": "<!-- repoheart:triage -->",
    "duplicate_detection": "<!-- repoheart:duplicate-check -->",
    "issue_resolution": "<!-- repoheart:resolution-check -->",
    "ci_repair": "<!-- repoheart:ci-repair -->",
    "conflict_resolution": "<!-- repoheart:conflict-resolution -->",
}

_SEVERITY_BADGES: dict[str, str] = {
    "critical": "🔴 Critical",
    "high": "🟠 High",
    "warning": "🟡 Warning",
    "info": "🔵 Info",
}


def format_issue_comment(comment: IssueComment, agent_name: str) -> str:
    """Format an IssueComment into a GitHub comment body with idempotency marker."""
    marker = ISSUE_AGENT_MARKERS.get(agent_name, f"<!-- repoheart:{agent_name} -->")
    badge = _SEVERITY_BADGES.get(comment.severity, comment.severity)

    lines: list[str] = [
        marker,
        f"**{comment.title}** {badge}",
        "",
        comment.body,
    ]

    if comment.references:
        lines.append("")
        lines.append("**References:** " + ", ".join(comment.references))

    lines.extend([
        "",
        "---",
        "_Automated by [RepoHeart](https://github.com/OpenAgentHQ/repo-heart)._",
    ])

    return "\n".join(lines)


def comment_already_posted(comments: list[dict[str, object]], agent_name: str) -> bool:
    """Return True if the agent's idempotency marker already appears in any comment."""
    marker = ISSUE_AGENT_MARKERS.get(agent_name, f"<!-- repoheart:{agent_name} -->")
    return any(marker in str(c.get("body", "")) for c in comments)
