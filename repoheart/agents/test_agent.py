"""TestCoverageAgent — test-impact mapping for changed modules."""

from __future__ import annotations

import json
import re

from repoheart.agents.base import Agent, AgentResult, Finding, ReviewComment
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.base import CompletionRequest, Message
from repoheart.safety.policy import RiskLevel

_SYSTEM_PROMPT = """\
You are a test coverage analyst. Given a list of changed Python modules and
their discovered test files, analyse whether the changes are adequately covered
by tests.

Consider:
- Are there test files that directly cover each changed module?
- Does the diff add new public functions/methods without corresponding tests?
- Does the diff modify existing logic in ways tests may not catch?

Return ONLY valid JSON in this exact format:
{
  "comments": [
    {
      "file": "<changed module path or null>",
      "line": <line number or null>,
      "severity": "error" | "warning" | "info",
      "title": "<short title, one phrase>",
      "body": "<what tests are missing or insufficient>",
      "suggestion": "<concrete suggestion for adding tests>"
    }
  ],
  "coverage_assessment": "good" | "partial" | "poor",
  "overall": "<one paragraph test coverage summary>"
}

If coverage looks adequate, return an empty comments array with coverage_assessment: good.\
"""


class TestCoverageAgent(Agent):
    name = "test"
    risk_level = RiskLevel.SAFE
    handles_events = [
        "pull_request.opened",
        "pull_request.synchronize",
        "pull_request.reopened",
    ]

    def run(self, context: AgentContext) -> AgentResult:
        if context.provider is None:
            return AgentResult(
                findings=[Finding(summary="No provider configured; skipping test coverage check")]
            )

        if not context.changed_files:
            return AgentResult(
                findings=[Finding(summary="No changed files; skipping test coverage check")]
            )

        py_files = [f for f in context.changed_files if f.endswith(".py")]
        if not py_files:
            return AgentResult(
                findings=[Finding(summary="No Python files changed; skipping test coverage check")]
            )

        mapping_lines = []
        for module in py_files:
            tests = context.test_mapping.get(module, [])
            test_str = ", ".join(tests) if tests else "none found"
            mapping_lines.append(f"  {module} → {test_str}")

        diff_excerpt = context.diff[:10_000] if context.diff else ""

        diff_section = (
            f"\n\nDiff excerpt (first 10 000 chars):\n```diff\n{diff_excerpt}\n```"
            if diff_excerpt
            else ""
        )
        user_content = (
            "Changed Python modules and their discovered test files:\n"
            + "\n".join(mapping_lines)
            + diff_section
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
                    summary="Provider error during test coverage check",
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
                        summary="Test coverage JSON parsing failed",
                        detail=f"{exc} — raw: {response.content[:300]}",
                    )
                ]
            )

        raw_comments = parsed.get("comments", [])
        assessment = str(parsed.get("coverage_assessment", "unknown"))
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
                    category="coverage",
                )
            )

        return AgentResult(
            review_comments=review_comments,
            needs_human_review=(assessment == "poor"),
            explanation=overall,
        )
