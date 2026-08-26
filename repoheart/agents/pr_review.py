"""PRReviewAgent — correctness review and synthesis over a PR diff."""

from __future__ import annotations

import json
import re

from repoheart.agents.base import Agent, AgentResult, Finding, ProposedAction, ReviewComment
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.base import CompletionRequest, Message
from repoheart.safety.policy import RiskLevel

_SYSTEM_PROMPT = """\
You are a senior software engineer performing a pull request code review.
Given the PR title, description, and unified diff, identify correctness issues,
logic errors, unhandled edge cases, and breaking API changes.

Return ONLY valid JSON in this exact format:
{
  "comments": [
    {
      "file": "<relative file path or null>",
      "line": <line number or null>,
      "severity": "critical" | "high" | "warning" | "info",
      "title": "<short title, one phrase>",
      "body": "<explanation of the issue>",
      "suggestion": "<how to fix it>"
    }
  ],
  "overall": "<one paragraph synthesis of the review>"
}

If the diff looks correct with no issues, return an empty comments array and a
brief positive overall summary. Focus only on correctness — not style.\
"""


class PRReviewAgent(Agent):
    name = "pr_review"
    risk_level = RiskLevel.SAFE
    handles_events = [
        "pull_request.opened",
        "pull_request.synchronize",
        "pull_request.reopened",
        "pull_request_review.submitted",
    ]

    def run(self, context: AgentContext) -> AgentResult:
        if context.provider is None:
            return AgentResult(
                findings=[Finding(summary="No provider configured; skipping PR review")]
            )

        if context.pr_data is None:
            return AgentResult(
                findings=[Finding(summary="No PR data in context; skipping PR review")]
            )

        if not context.diff:
            return AgentResult(
                findings=[Finding(summary="Empty diff; nothing to review")]
            )

        pr = context.pr_data
        title = pr.get("title", "")
        body = (pr.get("body") or "")[:1000]
        diff_excerpt = context.diff[:30_000]

        user_content = (
            f"PR Title: {title}\n\n"
            f"PR Description:\n{body}\n\n"
            f"Unified Diff:\n```diff\n{diff_excerpt}\n```"
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
                findings=[Finding(summary="Provider error during PR review", detail=str(exc))]
            )

        try:
            raw = re.sub(r"^```(?:json)?\s*", "", response.content.strip())
            raw = re.sub(r"\s*```$", "", raw)
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            return AgentResult(
                findings=[
                    Finding(
                        summary="PR review JSON parsing failed",
                        detail=f"{exc} — raw: {response.content[:300]}",
                    )
                ]
            )

        raw_comments = parsed.get("comments", [])
        overall = str(parsed.get("overall", ""))

        review_comments: list[ReviewComment] = []
        proposed_actions: list[ProposedAction] = []

        for item in raw_comments:
            if not isinstance(item, dict):
                continue
            sev = str(item.get("severity", "info"))
            review_comments.append(
                ReviewComment(
                    title=str(item.get("title", "")),
                    body=str(item.get("body", "")),
                    severity=sev,
                    file=item.get("file") or None,
                    line=item.get("line") or None,
                    suggestion=item.get("suggestion") or None,
                    category="correctness",
                )
            )

        has_critical = any(rc.severity in {"critical", "high"} for rc in review_comments)
        return AgentResult(
            review_comments=review_comments,
            proposed_actions=proposed_actions,
            needs_human_review=has_critical,
            explanation=overall,
        )
