"""CodeQualityAgent — synthesise linter and type-checker output for a PR."""

from __future__ import annotations

import json
import re

from repoheart.agents.base import Agent, AgentResult, Finding, ReviewComment
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.base import CompletionRequest, Message
from repoheart.safety.policy import RiskLevel

_SYSTEM_PROMPT = """\
You are a code quality assistant. Given the output from linters and type
checkers (ruff, mypy) run against the changed files in a pull request,
synthesise the most important actionable findings.

Ignore minor style nits. Focus on real errors, type violations, and warnings
that indicate likely bugs. Deduplicate and group related issues.

Return ONLY valid JSON in this exact format:
{
  "comments": [
    {
      "file": "<relative path or null>",
      "line": <line number or null>,
      "severity": "error" | "warning" | "info",
      "title": "<short title, one phrase>",
      "body": "<what it means and how to fix it>",
      "suggestion": "<concrete fix suggestion>",
      "tool": "<ruff|mypy|unknown>",
      "category": "<style|type_error|complexity|...>"
    }
  ],
  "overall": "<one paragraph summary of code quality>"
}

If there are no actionable issues, return an empty comments array.\
"""


class CodeQualityAgent(Agent):
    name = "code_quality"
    risk_level = RiskLevel.SAFE
    handles_events = [
        "pull_request.opened",
        "pull_request.synchronize",
        "pull_request.reopened",
    ]

    def run(self, context: AgentContext) -> AgentResult:
        if context.provider is None:
            return AgentResult(
                findings=[Finding(summary="No provider configured; skipping code quality check")]
            )

        if not context.changed_files:
            return AgentResult(
                findings=[Finding(summary="No changed files; skipping code quality check")]
            )

        if not context.linter_output:
            return AgentResult(
                findings=[Finding(summary="No linter output available; tools may not be installed")]
            )

        py_files = [f for f in context.changed_files if f.endswith(".py")]
        if not py_files:
            return AgentResult(
                findings=[Finding(summary="No Python files changed; skipping code quality check")]
            )

        tool_output = context.linter_output[:20_000]
        user_content = (
            f"Changed Python files: {', '.join(py_files)}\n\n"
            f"Linter / type-checker output:\n```\n{tool_output}\n```"
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
                    summary="Provider error during code quality check",
                    detail=str(exc),
                )]
            )

        try:
            raw = re.sub(r"^```(?:json)?\s*", "", response.content.strip())
            raw = re.sub(r"\s*```$", "", raw)
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            return AgentResult(
                findings=[
                    Finding(
                        summary="Code quality JSON parsing failed",
                        detail=f"{exc} — raw: {response.content[:300]}",
                    )
                ]
            )

        raw_comments = parsed.get("comments", [])
        overall = str(parsed.get("overall", ""))

        review_comments: list[ReviewComment] = []
        for item in raw_comments:
            if not isinstance(item, dict):
                continue
            review_comments.append(
                ReviewComment(
                    title=str(item.get("title", "")),
                    body=str(item.get("body", "")),
                    severity=str(item.get("severity", "info")),
                    file=item.get("file") or None,
                    line=item.get("line") or None,
                    suggestion=item.get("suggestion") or None,
                    category=str(item.get("category", "style")) or None,
                )
            )

        return AgentResult(review_comments=review_comments, explanation=overall)
