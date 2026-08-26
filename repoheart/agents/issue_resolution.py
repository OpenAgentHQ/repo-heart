"""IssueResolutionAgent — check whether an issue is already fixed by a merged PR."""

from __future__ import annotations

import json
import re

from repoheart.agents.base import Agent, AgentResult, Finding, IssueComment, ProposedAction
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.base import CompletionRequest, Message
from repoheart.safety.policy import ActionKind, RiskLevel

_SYSTEM_PROMPT = """\
You are a GitHub issue resolution checker. Given an issue and a merged pull \
request that references it, determine whether the PR likely resolves the issue.

Return ONLY valid JSON in this exact format:
{
  "resolved": true | false,
  "confidence": "high" | "medium" | "low",
  "pr_number": <int or null>,
  "explanation": "<brief explanation>"
}\
"""


class IssueResolutionAgent(Agent):
    name = "issue_resolution"
    risk_level = RiskLevel.SAFE
    handles_events = [
        "issues.opened",
        "issues.reopened",
        "issues.edited",
        "issues.closed",
        "issue_comment.created",
    ]

    def run(self, context: AgentContext) -> AgentResult:
        if context.provider is None:
            return AgentResult(
                findings=[Finding(summary="No provider configured; skipping resolution check")]
            )

        if context.issue_data is None:
            return AgentResult(
                findings=[Finding(summary="No issue data in context; skipping resolution check")]
            )

        # Only act on merged PRs — open PRs don't confirm a fix
        merged_prs = [
            pr for pr in context.linked_pull_requests
            if isinstance(pr.get("pull_request"), dict)
            and pr["pull_request"].get("merged_at") is not None
        ]

        if not merged_prs:
            return AgentResult(
                findings=[Finding(summary="No merged PRs found referencing this issue")]
            )

        issue = context.issue_data
        title = issue.get("title", "")
        body = (issue.get("body") or "")[:500]

        # Use the most recently merged PR (first in results)
        pr = merged_prs[0]
        pr_number = pr.get("number")
        pr_title = pr.get("title", "")
        pr_body = (pr.get("body") or "")[:500]

        user_content = (
            f"Issue:\nTitle: {title}\nBody: {body}\n\n"
            f"Merged PR #{pr_number}:\nTitle: {pr_title}\nBody: {pr_body}"
        )
        request = CompletionRequest(
            system=_SYSTEM_PROMPT,
            messages=[Message(role="user", content=user_content)],
            model=context.config.provider.model,
            temperature=0.0,
        )

        try:
            response = context.provider.complete(request)
        except Exception as exc:
            return AgentResult(
                findings=[Finding(
                    summary="Provider error during resolution check", detail=str(exc)
                )]
            )

        try:
            raw = re.sub(r"^```(?:json)?\s*", "", response.content.strip())
            raw = re.sub(r"\s*```$", "", raw)
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            return AgentResult(
                findings=[Finding(summary="Resolution check JSON parsing failed", detail=str(exc))]
            )

        resolved = bool(parsed.get("resolved", False))
        confidence = str(parsed.get("confidence", "low"))
        explanation = str(parsed.get("explanation", ""))
        resolved_pr = parsed.get("pr_number") or pr_number

        proposed_actions: list[ProposedAction] = []
        issue_comments: list[IssueComment] = []

        if resolved and confidence in ("high", "medium"):
            severity = "high" if confidence == "high" else "warning"
            issue_comments.append(
                IssueComment(
                    title="Possibly already fixed",
                    body=(
                        f"PR #{resolved_pr} may have resolved this issue.\n\n"
                        f"{explanation}\n\n"
                        "If this resolves your issue, please close it. "
                        "If the problem persists, let us know what's still happening."
                    ),
                    severity=severity,
                    references=[f"#{resolved_pr}"],
                )
            )

        if resolved and confidence == "high":
            proposed_actions.append(
                ProposedAction(
                    kind=ActionKind.ADD_LABEL,
                    payload={"labels": ["already-fixed"]},
                    reason=f"High-confidence resolution by PR #{resolved_pr}",
                )
            )

        status = "resolved" if resolved else "not resolved"
        summary = f"Resolution: {status} ({confidence} confidence)"
        return AgentResult(
            findings=[Finding(summary=summary, detail=explanation)],
            issue_comments=issue_comments,
            proposed_actions=proposed_actions,
        )
