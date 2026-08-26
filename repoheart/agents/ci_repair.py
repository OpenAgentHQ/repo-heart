"""CIRepairAgent — diagnose CI failures and propose scoped code fixes.

Triggered by ``workflow_run.completed`` and ``check_run.completed`` events.
Reads CI failure logs from context, identifies implicated files via the LLM,
and proposes minimal patches (MODIFY_CODE → COMMIT → PUSH_BRANCH) on a new
fix branch — never on the base branch.

Safety guarantees:
  * No force-push: PUSH_BRANCH payload never carries ``--force``.
  * No merge: ActionKind.MERGE does not exist in this codebase.
  * Low confidence (< 0.8) → ``needs_human_review=True``, zero write proposals.
  * Retry ceiling: the fix branch name encodes the run ID; if it already exists
    the orchestrator skips via idempotency.
  * Revert-on-failure: the orchestrator's test-verify gate drops COMMIT and
    PUSH_BRANCH proposals if local tests fail — there is nothing to revert.
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
)
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.base import CompletionRequest, Message
from repoheart.safety.policy import ActionKind, RiskLevel

_CONFIDENCE_THRESHOLD = 0.8
_LOG_MAX = 40_000
_FIX_BRANCH_PREFIX = "repoheart/fix-ci"

_SYSTEM_PROMPT = """\
You are an expert software engineer diagnosing a CI failure.
Given CI failure logs, identify the root cause and propose a minimal,
targeted code fix.

Return ONLY valid JSON in this exact format:
{
  "root_cause": "<one sentence describing what failed and why>",
  "implicated_files": ["<relative/path/to/file.py>", ...],
  "patches": [
    {
      "file": "<relative file path>",
      "description": "<what this patch does>",
      "search": "<exact lines to replace (verbatim)>",
      "replace": "<replacement lines>"
    }
  ],
  "confidence": <0.0 to 1.0>,
  "explanation": "<one paragraph: what failed, why, and what the fix does>"
}

Rules:
- Only propose changes to files that directly caused the failure.
- Keep patches minimal — the smallest change that fixes the test/lint error.
- If the root cause is ambiguous or requires understanding untested behaviour,
  set confidence < 0.8 and leave patches as an empty list.
- Never propose changes to CI configuration files or dependency lock files.
- Output only JSON, no prose before or after.\
"""


def _is_watched_workflow(run_name: str, watch_workflows: list[str]) -> bool:
    """Return True if ``run_name`` matches any configured watch pattern."""
    if not watch_workflows:
        return True  # no filter → watch everything
    lower = run_name.lower()
    return any(w.lower() in lower for w in watch_workflows)


def _extract_run_id(event_payload: dict[str, object]) -> str:
    """Extract a stable run identifier from the event payload."""
    for key in ("workflow_run", "check_run"):
        sub = event_payload.get(key)
        if isinstance(sub, dict):
            run_id = sub.get("id")
            if run_id is not None:
                return str(run_id)
    return "unknown"


class CIRepairAgent(Agent):
    name = "ci_repair"
    risk_level = RiskLevel.MEDIUM
    handles_events = ["workflow_run.completed", "check_run.completed"]

    def run(self, context: AgentContext) -> AgentResult:
        if context.provider is None:
            return AgentResult(
                findings=[Finding(summary="No provider configured; skipping CI repair")]
            )

        if not context.ci_logs:
            return AgentResult(
                findings=[Finding(summary="No CI logs available; skipping CI repair")]
            )

        # Respect watch_workflows filter
        workflow_run_data = context.workflow_run_data or {}
        run_name = str(workflow_run_data.get("name", ""))
        if not _is_watched_workflow(run_name, list(context.config.ci.watch_workflows)):
            return AgentResult(
                findings=[
                    Finding(
                        summary=f"Workflow '{run_name}' not in watch_workflows; skipping",
                    )
                ]
            )

        # Only act on failures
        conclusion = str(workflow_run_data.get("conclusion", "failure"))
        if conclusion not in {"failure", "timed_out", "cancelled"}:
            return AgentResult(
                findings=[Finding(summary=f"Workflow conclusion '{conclusion}' is not a failure")]
            )

        run_id = _extract_run_id(dict(context.event.payload))
        fix_branch = f"{_FIX_BRANCH_PREFIX}-{run_id}"

        logs_excerpt = context.ci_logs[:_LOG_MAX]
        request = CompletionRequest(
            system=_SYSTEM_PROMPT,
            messages=[
                Message(
                    role="user",
                    content=(
                        f"Repository: {context.event.repo_full_name}\n"
                        f"Workflow: {run_name}\n"
                        f"Conclusion: {conclusion}\n\n"
                        f"CI Failure Logs:\n```\n{logs_excerpt}\n```"
                    ),
                )
            ],
            model=context.config.provider.model,
            temperature=0.0,
        )

        try:
            response = context.provider.complete(request)
        except Exception as exc:
            return AgentResult(
                findings=[Finding(summary="Provider error during CI repair", detail=str(exc))]
            )

        parsed = _parse_repair_response(response.content)
        confidence = float(parsed.get("confidence", 0.0) or 0.0)
        root_cause = str(parsed.get("root_cause", ""))
        explanation = str(parsed.get("explanation", root_cause))
        raw_patches = parsed.get("patches", [])
        patches: list[dict[str, str]] = (
            [p for p in raw_patches if isinstance(p, dict)]
            if isinstance(raw_patches, list)
            else []
        )

        comment_body = (
            f"**Root cause:** {root_cause}\n\n"
            f"{explanation}"
        )
        if confidence < _CONFIDENCE_THRESHOLD or not patches:
            comment_body += (
                f"\n\n_Confidence too low ({confidence:.0%}) for an automated fix. "
                f"Manual intervention required._"
            )
            return AgentResult(
                issue_comments=[
                    IssueComment(
                        title="CI failure diagnosed — manual fix required",
                        body=comment_body,
                        severity="high",
                    )
                ],
                needs_human_review=True,
                confidence=confidence,
                explanation=explanation,
            )

        # High confidence → propose fix branch + patches + commit + push
        proposed_actions: list[ProposedAction] = []

        proposed_actions.append(
            ProposedAction(
                kind=ActionKind.CREATE_BRANCH,
                payload={"name": fix_branch, "from_ref": "HEAD"},
                reason=f"Create fix branch for CI run {run_id}",
            )
        )

        for patch in patches:
            proposed_actions.append(
                ProposedAction(
                    kind=ActionKind.MODIFY_CODE,
                    payload={
                        "path": patch.get("file", ""),
                        "search": patch.get("search", ""),
                        "replace": patch.get("replace", ""),
                        "description": patch.get("description", ""),
                    },
                    reason=f"CI repair patch: {patch.get('description', '')}",
                )
            )

        proposed_actions.append(
            ProposedAction(
                kind=ActionKind.COMMIT,
                payload={
                    "message": f"fix(ci): repair CI failure from run {run_id}\n\n{root_cause}",
                    "paths": [p.get("file", "") for p in patches],
                    "branch": fix_branch,
                },
                reason=f"Commit CI repair for run {run_id}",
            )
        )

        proposed_actions.append(
            ProposedAction(
                kind=ActionKind.PUSH_BRANCH,
                payload={"branch": fix_branch, "force": False},
                reason=f"Push fix branch {fix_branch} for CI run {run_id}",
            )
        )

        comment_body += (
            f"\n\n**Proposed fix branch:** `{fix_branch}`\n"
            f"Patches {len(patches)} file(s). Pending Safety Gate approval and "
            f"local test verification before commit."
        )

        return AgentResult(
            issue_comments=[
                IssueComment(
                    title="CI failure — automated fix proposed",
                    body=comment_body,
                    severity="warning",
                )
            ],
            proposed_actions=proposed_actions,
            confidence=confidence,
            explanation=explanation,
        )


def _parse_repair_response(content: str) -> dict[str, Any]:
    """Extract JSON from a provider response; return empty dict on failure."""
    try:
        raw = re.sub(r"^```(?:json)?\s*", "", content.strip())
        raw = re.sub(r"\s*```$", "", raw)
        result: dict[str, Any] = json.loads(raw)
        return result
    except (json.JSONDecodeError, ValueError):
        return {}
