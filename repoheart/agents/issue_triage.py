"""IssueTriageAgent — classify, label, and summarise a GitHub issue."""

from __future__ import annotations

import json
import re

from repoheart.agents.base import Agent, AgentResult, Finding, IssueComment, ProposedAction
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.base import CompletionRequest, Message
from repoheart.safety.policy import ActionKind, RiskLevel

_SYSTEM_PROMPT = """\
You are a GitHub issue triage assistant. Given an issue title, body, and the \
repository's available labels, classify the issue and produce structured output.

Return ONLY valid JSON in this exact format:
{
  "type": "bug" | "enhancement" | "question" | "documentation" | "invalid",
  "priority": "high" | "medium" | "low",
  "component": "<component name or null>",
  "labels": ["<label name>", ...],
  "summary": "<one concise paragraph triage summary>"
}

Use only label names from the provided available_labels list. \
If no labels fit, use an empty array.\
"""

_PRIORITY_SEVERITY: dict[str, str] = {
    "high": "high",
    "medium": "warning",
    "low": "info",
}


class IssueTriageAgent(Agent):
    name = "issue_triage"
    risk_level = RiskLevel.SAFE
    handles_events = [
        "issues.opened",
        "issues.reopened",
        "issues.edited",
        "issue_comment.created",
    ]

    def run(self, context: AgentContext) -> AgentResult:
        if context.provider is None:
            return AgentResult(
                findings=[Finding(summary="No provider configured; skipping triage")]
            )

        if context.issue_data is None:
            return AgentResult(
                findings=[Finding(summary="No issue data in context; skipping triage")]
            )

        issue = context.issue_data
        title = issue.get("title", "")
        body = (issue.get("body") or "")[:2000]
        available_labels = [
            lbl["name"] for lbl in context.repo_labels if isinstance(lbl, dict) and "name" in lbl
        ]

        user_content = (
            f"Title: {title}\n\nBody:\n{body}\n\n"
            f"Available labels: {', '.join(available_labels) or 'none'}"
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
                findings=[Finding(summary="Provider error during triage", detail=str(exc))]
            )

        try:
            raw = re.sub(r"^```(?:json)?\s*", "", response.content.strip())
            raw = re.sub(r"\s*```$", "", raw)
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            return AgentResult(
                findings=[
                    Finding(
                        summary="Triage JSON parsing failed",
                        detail=f"{exc} — raw: {response.content[:300]}",
                    )
                ]
            )

        triage_type = str(parsed.get("type", "unknown"))
        priority = str(parsed.get("priority", "medium"))
        component = parsed.get("component") or "—"
        summary = str(parsed.get("summary", ""))
        labels = [lbl for lbl in parsed.get("labels", []) if lbl in available_labels]

        proposed_actions: list[ProposedAction] = []

        if labels:
            proposed_actions.append(
                ProposedAction(
                    kind=ActionKind.ADD_LABEL,
                    payload={"labels": labels},
                    reason=f"Issue classified as {triage_type} with priority {priority}",
                )
            )

        severity = _PRIORITY_SEVERITY.get(priority, "info")
        comment_body = (
            f"{summary}\n\n"
            f"- **Type:** {triage_type}\n"
            f"- **Priority:** {priority}\n"
            f"- **Component:** {component}"
        )
        issue_comments = [
            IssueComment(
                title="Issue Triage",
                body=comment_body,
                severity=severity,
            )
        ]

        finding = Finding(summary=f"Triage: {triage_type}, priority {priority}", detail=summary)
        return AgentResult(
            findings=[finding],
            issue_comments=issue_comments,
            proposed_actions=proposed_actions,
        )
