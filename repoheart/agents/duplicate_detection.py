"""DuplicateDetectionAgent — find likely duplicate issues via LLM reranking."""

from __future__ import annotations

import json
import re

from repoheart.agents.base import Agent, AgentResult, Finding, ProposedAction
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.base import CompletionRequest, Message
from repoheart.safety.policy import ActionKind, RiskLevel

_SYSTEM_PROMPT = """\
You are a GitHub duplicate issue detector. Given a new issue and a list of \
existing open issues, identify which (if any) are true duplicates or describe \
the same underlying problem.

Return ONLY valid JSON in this exact format:
{
  "duplicates": [
    {"number": <int>, "confidence": "high" | "medium" | "low", "reason": "<brief explanation>"}
  ]
}

Only include issues that are genuinely duplicates. An empty array is correct \
if there are no duplicates.\
"""

_DUPLICATE_COMMENT = """\
<!-- repoheart:duplicate-check -->
**Possible Duplicate Detected**

This issue may be a duplicate of:
{links}

Please review and close if confirmed.

_Automated duplicate detection by [RepoHeart](https://github.com/OpenAgentHQ/repo-heart)._\
"""

_RELATED_COMMENT = """\
<!-- repoheart:duplicate-check -->
**Possibly Related Issues**

These existing issues may be related:
{links}

_Automated duplicate detection by [RepoHeart](https://github.com/OpenAgentHQ/repo-heart)._\
"""


class DuplicateDetectionAgent(Agent):
    name = "duplicate_detection"
    risk_level = RiskLevel.SAFE
    handles_events = ["issues.opened", "issues.reopened", "issues.edited"]

    def run(self, context: AgentContext) -> AgentResult:
        if context.provider is None:
            return AgentResult(
                findings=[Finding(summary="No provider configured; skipping duplicate detection")]
            )

        if context.issue_data is None:
            return AgentResult(
                findings=[Finding(summary="No issue data in context; skipping duplicate detection")]
            )

        if not context.candidate_issues:
            return AgentResult(findings=[Finding(summary="No candidate issues to compare against")])

        issue = context.issue_data
        title = issue.get("title", "")
        body = (issue.get("body") or "")[:500]

        candidate_lines = []
        for c in context.candidate_issues[:10]:
            cnum = c.get("number", "?")
            ctitle = c.get("title", "")
            cbody = (c.get("body") or "")[:200]
            candidate_lines.append(f"#{cnum}: {ctitle}\n{cbody}")

        user_content = (
            f"New issue:\nTitle: {title}\nBody: {body}\n\n---\n\n"
            f"Existing issues:\n\n" + "\n\n---\n\n".join(candidate_lines)
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
                    summary="Provider error during duplicate detection", detail=str(exc)
                )]
            )

        try:
            raw = re.sub(r"^```(?:json)?\s*", "", response.content.strip())
            raw = re.sub(r"\s*```$", "", raw)
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            return AgentResult(
                findings=[Finding(
                    summary="Duplicate detection JSON parsing failed", detail=str(exc)
                )]
            )

        duplicates = parsed.get("duplicates", [])
        high = [d for d in duplicates if d.get("confidence") == "high"]
        medium = [d for d in duplicates if d.get("confidence") == "medium"]

        proposed_actions: list[ProposedAction] = []

        if high:
            links = "\n".join(f"- #{d['number']}: {d.get('reason', '')}" for d in high)
            proposed_actions.append(
                ProposedAction(
                    kind=ActionKind.ADD_LABEL,
                    payload={"labels": ["duplicate"]},
                    reason=f"High-confidence duplicate of #{high[0]['number']}",
                )
            )
            proposed_actions.append(
                ProposedAction(
                    kind=ActionKind.POST_COMMENT,
                    payload={"body": _DUPLICATE_COMMENT.format(links=links)},
                    reason="Notify submitter of detected duplicate",
                )
            )
        elif medium:
            links = "\n".join(f"- #{d['number']}: {d.get('reason', '')}" for d in medium)
            proposed_actions.append(
                ProposedAction(
                    kind=ActionKind.POST_COMMENT,
                    payload={"body": _RELATED_COMMENT.format(links=links)},
                    reason="Notify submitter of possibly related issues",
                )
            )

        detail = f"{len(high)} high-confidence, {len(medium)} medium-confidence duplicates found"
        return AgentResult(
            findings=[Finding(summary="Duplicate detection complete", detail=detail)],
            proposed_actions=proposed_actions,
        )
