"""ConflictResolutionAgent — semantic conflict explanation and resolution proposals.

Triggered on pull_request.opened/synchronize and push events.  When a PR has
merge conflicts this agent analyses the conflicting sections and either:

  * High confidence (>= 0.7): proposes ``MODIFY_CODE`` patches with resolved
    content plus a ``ReviewComment`` or ``IssueComment`` explaining the fix.
  * Low confidence (< 0.7): sets ``needs_human_review=True`` and returns a
    comment explaining the conflict without attempting a fix — the agent
    never blindly picks ``ours`` or ``theirs``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from repoheart.agents.base import (
    Agent,
    AgentResult,
    Finding,
    IssueComment,
    ProposedAction,
    ReviewComment,
)
from repoheart.git_ops.conflicts import ConflictBlock, ConflictFile
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.base import CompletionRequest, Message
from repoheart.safety.policy import ActionKind, RiskLevel

_CONFIDENCE_THRESHOLD = 0.7

_SYSTEM_PROMPT = """\
You are an expert software engineer resolving merge conflicts.
You will be given one or more conflict sections from a file (each with "ours"
and "theirs" content) plus surrounding context.

For each conflict block return ONLY valid JSON in this exact format:
{
  "resolution": "<the resolved content that replaces the entire conflict block>",
  "explanation": "<one sentence explaining why this resolution is correct>",
  "confidence": <0.0 to 1.0>
}

Rules:
- If the correct resolution is ambiguous, set confidence < 0.7 and leave
  resolution as an empty string — do NOT guess.
- Never simply pick one side; understand what both sides intended.
- Output only JSON, no prose before or after.\
"""


def _block_prompt(block: ConflictBlock, file_path: str, index: int) -> str:
    return (
        f"File: {file_path}\n"
        f"Conflict #{index + 1}\n\n"
        f"Context before conflict:\n```\n{block.context_before[:500]}\n```\n\n"
        f"<<<<<<< ours\n{block.ours}\n=======\n{block.theirs}\n>>>>>>> theirs\n"
    )


class ConflictResolutionAgent(Agent):
    name = "conflict_resolution"
    risk_level = RiskLevel.MEDIUM
    handles_events = [
        "pull_request.opened",
        "pull_request.synchronize",
        "push",
    ]

    def run(self, context: AgentContext) -> AgentResult:
        if context.provider is None:
            return AgentResult(
                findings=[Finding(summary="No provider configured; skipping conflict resolution")]
            )

        is_pr_event = context.event.event_name == "pull_request"

        # Check if PR is even mergeable before spending LLM calls
        if is_pr_event and context.pr_data is not None:
            mergeable = context.pr_data.get("mergeable")
            if mergeable is True:
                return AgentResult(
                    findings=[Finding(summary="PR is cleanly mergeable; no conflicts to resolve")]
                )

        conflict_files: list[ConflictFile] = list(context.conflict_files)

        if not conflict_files:
            if not context.diff:
                return AgentResult(
                    findings=[Finding(summary="No conflict data available; skipping")]
                )
            # Fall back to diff-based analysis when no conflict markers found
            return self._analyze_from_diff(context, is_pr_event)

        return self._analyze_conflict_files(context, conflict_files, is_pr_event)

    def _analyze_conflict_files(
        self,
        context: AgentContext,
        conflict_files: list[ConflictFile],
        is_pr_event: bool,
    ) -> AgentResult:
        review_comments: list[ReviewComment] = []
        issue_comments: list[IssueComment] = []
        proposed_actions: list[ProposedAction] = []
        needs_human = False
        explanations: list[str] = []

        for cf in conflict_files:
            min_confidence = cf.resolution_confidence
            if min_confidence < _CONFIDENCE_THRESHOLD:
                needs_human = True
                msg = (
                    f"Conflict in `{cf.path}` has low resolution confidence "
                    f"({min_confidence:.0%}). Manual review required."
                )
                if is_pr_event:
                    review_comments.append(
                        ReviewComment(
                            title=f"Merge conflict in {cf.path}",
                            body=msg,
                            severity="high",
                            file=cf.path,
                            category="correctness",
                        )
                    )
                else:
                    issue_comments.append(
                        IssueComment(
                            title=f"Merge conflict in {cf.path}",
                            body=msg,
                            severity="high",
                        )
                    )
                continue

            for idx, block in enumerate(cf.blocks):
                if context.provider is None:
                    needs_human = True
                    break
                prompt = _block_prompt(block, cf.path, idx)
                request = CompletionRequest(
                    system=_SYSTEM_PROMPT,
                    messages=[Message(role="user", content=prompt)],
                    model=context.config.provider.model,
                    temperature=0.0,
                )
                try:
                    response = context.provider.complete(request)
                except Exception as exc:
                    needs_human = True
                    explanations.append(f"Provider error for {cf.path}: {exc}")
                    continue

                parsed = _parse_resolution_response(response.content)
                confidence = float(parsed.get("confidence", 0.0) or 0.0)
                resolution = str(parsed.get("resolution", "")).strip()
                explanation = str(parsed.get("explanation", ""))

                if confidence < _CONFIDENCE_THRESHOLD or not resolution:
                    needs_human = True
                    msg = (
                        f"Conflict #{idx + 1} in `{cf.path}` could not be resolved "
                        f"automatically (confidence {confidence:.0%}). "
                        f"{explanation}"
                    )
                    if is_pr_event:
                        review_comments.append(
                            ReviewComment(
                                title=f"Unresolvable conflict in {cf.path}",
                                body=msg,
                                severity="high",
                                file=cf.path,
                                category="correctness",
                            )
                        )
                    else:
                        issue_comments.append(
                            IssueComment(
                                title=f"Unresolvable conflict in {cf.path}",
                                body=msg,
                                severity="high",
                            )
                        )
                    continue

                explanations.append(f"{cf.path}: {explanation}")
                proposed_actions.append(
                    ProposedAction(
                        kind=ActionKind.MODIFY_CODE,
                        payload={
                            "path": cf.path,
                            "resolved_content": resolution,
                            "conflict_index": idx,
                            "explanation": explanation,
                        },
                        reason=f"Resolve conflict #{idx + 1} in {cf.path}: {explanation}",
                    )
                )
                if is_pr_event:
                    review_comments.append(
                        ReviewComment(
                            title=f"Conflict resolved in {cf.path}",
                            body=f"Proposed resolution (confidence {confidence:.0%}):\n\n"
                            f"```\n{resolution[:500]}\n```\n\n{explanation}",
                            severity="info",
                            file=cf.path,
                            suggestion=resolution[:500] if len(resolution) <= 500 else None,
                            category="correctness",
                        )
                    )
                else:
                    issue_comments.append(
                        IssueComment(
                            title=f"Conflict resolved in {cf.path}",
                            body=(
                                f"Proposed resolution:\n\n"
                                f"```\n{resolution[:500]}\n```\n\n{explanation}"
                            ),
                            severity="info",
                        )
                    )

        return AgentResult(
            review_comments=review_comments,
            issue_comments=issue_comments,
            proposed_actions=proposed_actions,
            needs_human_review=needs_human,
            explanation="; ".join(explanations) if explanations else "",
        )

    def _analyze_from_diff(self, context: AgentContext, is_pr_event: bool) -> AgentResult:
        """Fallback: explain potential conflicts from the PR diff when no markers found."""
        mergeable = context.pr_data.get("mergeable") if context.pr_data else None

        if mergeable is not False:
            return AgentResult(
                findings=[Finding(summary="PR appears mergeable; no conflict analysis needed")]
            )

        msg = (
            "This pull request has merge conflicts that must be resolved before merging. "
            "RepoHeart detected the conflict via GitHub's mergeable status but could not "
            "retrieve conflict markers for automated resolution. Please resolve conflicts "
            "manually or rebase your branch."
        )
        if is_pr_event:
            return AgentResult(
                review_comments=[
                    ReviewComment(
                        title="Merge conflicts detected",
                        body=msg,
                        severity="high",
                        category="correctness",
                    )
                ],
                needs_human_review=True,
            )
        return AgentResult(
            issue_comments=[
                IssueComment(title="Merge conflicts detected", body=msg, severity="high")
            ],
            needs_human_review=True,
        )


def _parse_resolution_response(content: str) -> dict[str, Any]:
    """Extract JSON from a provider response; return empty dict on failure."""
    try:
        raw = re.sub(r"^```(?:json)?\s*", "", content.strip())
        raw = re.sub(r"\s*```$", "", raw)
        result: dict[str, Any] = json.loads(raw)
        return result
    except (json.JSONDecodeError, ValueError):
        return {}
