"""SecurityAgent — secret scan and dependency audit on a PR diff."""

from __future__ import annotations

import json
import re

from repoheart.agents.base import Agent, AgentResult, Finding, ProposedAction, ReviewComment
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.base import CompletionRequest, Message
from repoheart.safety.policy import ActionKind, RiskLevel

_SYSTEM_PROMPT = """\
You are a security-focused code reviewer. Given a unified diff and optional
secret-scan output, identify security issues introduced by this pull request.

Look for:
- Hardcoded credentials, API keys, tokens, passwords, or secrets
- SQL / command / path injection vectors
- Unsafe deserialization or eval() / exec() on untrusted input
- New dependencies added in requirements files — flag any that are
  known-vulnerable or suspicious
- Insecure cryptography (MD5, SHA1 for passwords, weak random)
- Overly broad permissions or privilege escalation patterns

Return ONLY valid JSON in this exact format:
{
  "comments": [
    {
      "file": "<relative path or null>",
      "line": <line number or null>,
      "severity": "critical" | "high" | "medium" | "low",
      "title": "<short title, one phrase>",
      "body": "<what the issue is and how to remediate it>",
      "suggestion": "<concrete fix>",
      "category": "<hardcoded_secret|injection|insecure_crypto|...>"
    }
  ],
  "has_secrets": <true | false>,
  "overall": "<one paragraph security summary>"
}

If no issues are found, return an empty comments array and has_secrets: false.\
"""


class SecurityAgent(Agent):
    name = "security"
    risk_level = RiskLevel.SAFE
    handles_events = [
        "pull_request.opened",
        "pull_request.synchronize",
        "pull_request.reopened",
    ]

    def run(self, context: AgentContext) -> AgentResult:
        if context.provider is None:
            return AgentResult(
                findings=[Finding(summary="No provider configured; skipping security scan")]
            )

        if context.pr_data is None:
            return AgentResult(
                findings=[Finding(summary="No PR data in context; skipping security scan")]
            )

        if not context.diff:
            return AgentResult(
                findings=[Finding(summary="Empty diff; nothing to scan")]
            )

        diff_excerpt = context.diff[:30_000]
        secret_section = (
            f"\nSecret scan output:\n```\n{context.secret_scan_output[:5_000]}\n```"
            if context.secret_scan_output
            else ""
        )

        user_content = (
            f"PR title: {context.pr_data.get('title', '')}\n\n"
            f"Unified Diff:\n```diff\n{diff_excerpt}\n```"
            f"{secret_section}"
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
                findings=[Finding(summary="Provider error during security scan", detail=str(exc))]
            )

        try:
            raw = re.sub(r"^```(?:json)?\s*", "", response.content.strip())
            raw = re.sub(r"\s*```$", "", raw)
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            return AgentResult(
                findings=[
                    Finding(
                        summary="Security scan JSON parsing failed",
                        detail=f"{exc} — raw: {response.content[:300]}",
                    )
                ]
            )

        raw_comments = parsed.get("comments", [])
        has_secrets = bool(parsed.get("has_secrets", False))
        overall = str(parsed.get("overall", ""))

        review_comments: list[ReviewComment] = []
        proposed_actions: list[ProposedAction] = []

        for item in raw_comments:
            if not isinstance(item, dict):
                continue
            sev = str(item.get("severity", "medium"))
            review_comments.append(
                ReviewComment(
                    title=str(item.get("title", "")),
                    body=str(item.get("body", "")),
                    severity=sev,
                    file=item.get("file") or None,
                    line=item.get("line") or None,
                    suggestion=item.get("suggestion") or None,
                    category=str(item.get("category", "security")) or None,
                )
            )

        has_high_sev = any(
            rc.severity in {"critical", "high"} for rc in review_comments
        )
        if has_high_sev or has_secrets:
            proposed_actions.append(
                ProposedAction(
                    kind=ActionKind.ADD_LABEL,
                    payload={"labels": ["security-review"]},
                    reason="High-severity or secret detected in diff",
                )
            )

        return AgentResult(
            review_comments=review_comments,
            proposed_actions=proposed_actions,
            needs_human_review=has_high_sev or has_secrets,
            explanation=overall,
        )
