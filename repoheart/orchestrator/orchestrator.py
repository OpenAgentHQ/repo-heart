"""Orchestrator — sequences agent execution for a single event.

The Orchestrator is the only component that calls agents, feeds results to the
Safety Gate, and dispatches allowed actions. It catches per-agent exceptions so
one failing agent never aborts the entire run.
"""

from __future__ import annotations

import contextlib
import glob
import os
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from repoheart.agents.base import Agent, AgentResult, ProposedAction
from repoheart.agents.registry import AGENT_REGISTRY
from repoheart.config.schema import RepoHeartConfig
from repoheart.events.types import InternalEvent
from repoheart.git_ops.repo import GitRepo
from repoheart.github_ops.client import GitHubClient
from repoheart.idempotency.fingerprint import fingerprint_for_event
from repoheart.idempotency.markers import IdempotencyMarkers
from repoheart.observability.logger import StructuredLogger
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.orchestrator.issue_flow import comment_already_posted, format_issue_comment
from repoheart.orchestrator.pr_flow import already_reviewed, consolidate
from repoheart.providers.base import CompletionRequest, CompletionResponse, Provider
from repoheart.retrieval.budget import BudgetExceededError, RunBudget
from repoheart.retrieval.layer import RetrievalLayer, RetrievalQuery
from repoheart.safety.gate import SafetyGate
from repoheart.safety.policy import ActionKind, Decision

_PR_AGENT_NAMES = {"pr_review", "code_quality", "security", "test"}

# ── Deterministic PR context helpers (no LLM, no GitHub) ─────────────────────

def _run_linters(py_files: list[str]) -> str:
    """Run ruff and mypy on the given Python files; return combined output.

    Returns an empty string if the tools are not installed or all files
    are missing from disk (e.g. deleted in the PR).
    """
    existing = [f for f in py_files if os.path.isfile(f)]
    if not existing:
        return ""

    parts: list[str] = []

    # ruff
    try:
        result = subprocess.run(
            ["ruff", "check", "--output-format=concise", *existing],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.stdout.strip():
            parts.append(f"=== ruff ===\n{result.stdout.strip()}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # mypy
    try:
        result = subprocess.run(
            ["mypy", "--no-error-summary", *existing],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.stdout.strip():
            parts.append(f"=== mypy ===\n{result.stdout.strip()}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    combined = "\n\n".join(parts)
    return combined[:20_000]


def _scan_secrets(diff: str) -> str:
    """Run detect-secrets against the diff; return raw output.

    Returns an empty string if the tool is not installed.
    """
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".diff", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(diff)
            tmp_path = tmp.name

        result = subprocess.run(
            ["detect-secrets", "scan", tmp_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip()
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        return output[:5_000]
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""


def _filter_to_diff(inline_comments: list[dict[str, Any]], diff: str) -> list[dict[str, Any]]:
    """Remove inline comments for files not present in the diff.

    Prevents GitHub 422 errors for comments outside the diff hunk.
    """
    files_in_diff = {
        line[6:] for line in diff.splitlines() if line.startswith("+++ b/")
    }
    return [c for c in inline_comments if c.get("path") in files_in_diff]


def _map_tests(changed_files: list[str], repo_root: str) -> dict[str, list[str]]:
    """Map each changed Python module to candidate test files under tests/.

    Uses simple naming conventions:
      src/foo/bar.py  →  look for tests/**/test_bar.py  and  tests/**/bar_test.py
    """
    mapping: dict[str, list[str]] = {}
    for filepath in changed_files:
        if not filepath.endswith(".py"):
            continue
        stem = os.path.splitext(os.path.basename(filepath))[0]
        patterns = [
            os.path.join(repo_root, "tests", "**", f"test_{stem}.py"),
            os.path.join(repo_root, "tests", "**", f"{stem}_test.py"),
        ]
        found: list[str] = []
        for pattern in patterns:
            matches = glob.glob(pattern, recursive=True)
            found.extend(os.path.relpath(m, repo_root) for m in matches)
        mapping[filepath] = found
    return mapping


def _extract_terms(pr_data: dict[str, Any] | None, diff: str) -> list[str]:
    """Extract search terms from PR title and diff for the retrieval layer."""
    terms: list[str] = []
    if pr_data:
        title = str(pr_data.get("title", "")).strip()
        if title:
            terms.append(title)
    for line in diff.splitlines()[:100]:
        if line.startswith("+") and not line.startswith("+++"):
            stripped = line[1:].strip()
            if len(stripped) > 10:
                terms.append(stripped[:80])
                break
    return terms[:3]


class _BudgetedProvider(Provider):
    """Thin wrapper that charges RunBudget on every complete() call."""

    def __init__(self, inner: Provider, budget: RunBudget) -> None:
        self._inner = inner
        self._budget = budget

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        self._budget.charge_llm_call()
        return self._inner.complete(request)

    def supports_tools(self) -> bool:
        return self._inner.supports_tools()

    def provider_name(self) -> str:
        return self._inner.provider_name()


@dataclass
class RunSummary:
    """Aggregate result of a single orchestrator run."""

    event: InternalEvent
    agents_run: list[str] = field(default_factory=list)
    actions_taken: int = 0
    actions_escalated: int = 0
    actions_denied: int = 0
    errors: list[str] = field(default_factory=list)


class Orchestrator:
    """Sequences agent execution, gates actions, and dispatches writes."""

    def __init__(
        self,
        config: RepoHeartConfig,
        github_client: GitHubClient,
        git_repo: GitRepo,
        safety_gate: SafetyGate,
        markers: IdempotencyMarkers,
        logger: StructuredLogger,
        provider_factory: Callable[[str], Provider] | None = None,
        retrieval_layer: RetrievalLayer | None = None,
    ) -> None:
        self._config = config
        self._github = github_client
        self._git = git_repo
        self._gate = safety_gate
        self._markers = markers
        self._logger = logger
        self._provider_factory = provider_factory
        self._retrieval_layer = retrieval_layer
        self._run_budget: RunBudget | None = None

    def run(self, event: InternalEvent, agent_names: list[str]) -> RunSummary:
        """Execute the pipeline for a routed event.

        For each agent:
        1. Check idempotency — skip if already processed.
        2. Build AgentContext (pre-fetch relevant GitHub data).
        3. Instantiate agent from registry.
        4. Call agent.run(context) — catch exceptions, log, continue.
        5. Validate agent's risk ceiling.
        6. For each proposed action: gate → execute / escalate / deny.

        For PR events, after all PR agents run their individual proposed actions
        are dispatched first, then a single consolidated review comment is posted
        (idempotent — skipped if already present).
        """
        summary = RunSummary(event=event)
        pr_agent_results: dict[str, AgentResult] = {}
        self._run_budget = RunBudget(limits=self._config.scale.limits)

        for agent_name in agent_names:
            try:
                self._run_budget.check_runtime()
            except BudgetExceededError as budget_exc:
                msg = f"budget ceiling hit before {agent_name}: {budget_exc}"
                self._logger.log(
                    event_msg="budget_ceiling_hit",
                    agent=agent_name,
                    reason=str(budget_exc),
                )
                summary.errors.append(msg)
                break
            fingerprint = fingerprint_for_event(event, agent_name)

            # 1. Idempotency check
            entity_number = self._extract_entity_number(event)
            if entity_number is not None and self._github._token:
                already_done = self._markers.has_been_processed(
                    event.repo_full_name, entity_number, fingerprint
                )
                result_label = "seen" if already_done else "not_seen"
            else:
                already_done = False
                result_label = "skipped_no_token"

            self._logger.log(
                event_msg="idempotency_check",
                agent=agent_name,
                fingerprint=fingerprint[:16] + "...",
                result=result_label,
            )

            if already_done:
                continue

            # 2. Build context
            context = self._build_context(event, agent_name, fingerprint)

            # 3 & 4. Instantiate and run agent
            agent_class = AGENT_REGISTRY.get(agent_name)
            if agent_class is None:
                self._logger.log(
                    event_msg="agent_skip",
                    agent=agent_name,
                    reason="not_in_registry",
                )
                continue

            agent: Agent = agent_class()
            try:
                result: AgentResult = agent.run(context)
            except Exception as exc:
                msg = f"agent '{agent_name}' raised {type(exc).__name__}: {exc}"
                self._logger.log(event_msg="agent_error", agent=agent_name, error=str(exc))
                summary.errors.append(msg)
                continue

            # 5. Validate ceiling
            try:
                agent.validate_ceiling(result)
            except ValueError as exc:
                msg = f"agent '{agent_name}' ceiling violation: {exc}"
                self._logger.log(
                    event_msg="agent_ceiling_violation", agent=agent_name, error=str(exc)
                )
                summary.errors.append(msg)
                continue

            summary.agents_run.append(agent_name)
            self._logger.log(
                event_msg="agent_run",
                agent=agent_name,
                status="ok",
                findings=len(result.findings),
                actions=len(result.proposed_actions),
            )

            # Collect PR agent results for consolidated comment (posted after loop)
            if agent_name in _PR_AGENT_NAMES:
                pr_agent_results[agent_name] = result

            # 6. Gate and dispatch per-agent proposed actions (labels, etc.)
            for action in result.proposed_actions:
                decision = self._gate.authorize(action, agent_name)
                if decision == Decision.ALLOW:
                    self._execute_action(action, event, decision)
                    summary.actions_taken += 1
                elif decision == Decision.ESCALATE:
                    self._post_escalation(action, agent_name, event)
                    summary.actions_escalated += 1
                else:
                    self._logger.log(
                        event_msg="action_denied",
                        agent=agent_name,
                        action_kind=action.kind.value,
                    )
                    summary.actions_denied += 1

            # Deliver IssueComment objects (issue agents only)
            if result.issue_comments:
                taken, escalated = self._deliver_issue_comments(result, agent_name, event)
                summary.actions_taken += taken
                summary.actions_escalated += escalated

        # Post one consolidated PR review comment after all PR agents have run
        if pr_agent_results:
            taken, escalated = self._post_consolidated_review(pr_agent_results, event)
            summary.actions_taken += taken
            summary.actions_escalated += escalated

        return summary

    def _build_context(
        self,
        event: InternalEvent,
        agent_name: str,
        fingerprint: str,
    ) -> AgentContext:
        """Pre-fetch data from GitHub and assemble AgentContext."""
        issue_data: dict[str, Any] | None = None
        pr_data: dict[str, Any] | None = None
        repo_labels: list[dict[str, Any]] = []
        candidate_issues: list[dict[str, Any]] = []
        linked_pull_requests: list[dict[str, Any]] = []
        diff: str = ""
        changed_files: list[str] = []
        linter_output: str = ""
        secret_scan_output: str = ""
        test_mapping: dict[str, list[str]] = {}

        provider: Provider | None = None
        if self._provider_factory is not None:
            base_provider = self._provider_factory(agent_name)
            provider = (
                _BudgetedProvider(base_provider, self._run_budget)
                if self._run_budget is not None
                else base_provider
            )

        if not self._github._token:
            return AgentContext(
                event=event,
                config=self._config,
                provider=provider,
                fingerprint=fingerprint,
            )

        entity_number = self._extract_entity_number(event)
        if entity_number is not None:
            try:
                if event.event_name == "issues":
                    issue_data = self._github.get_issue(
                        event.repo_full_name, entity_number
                    )
                elif event.event_name == "pull_request":
                    pr_data = self._github.get_pull_request(
                        event.repo_full_name, entity_number
                    )
            except Exception as exc:
                self._logger.log(
                    event_msg="context_fetch_error",
                    agent=agent_name,
                    error=str(exc),
                )

        # Agent-specific pre-fetches
        try:
            if agent_name == "issue_triage":
                repo_labels = self._github.list_labels(event.repo_full_name)
            elif agent_name == "duplicate_detection" and issue_data is not None:
                title = str(issue_data.get("title", ""))[:100]
                current_number = issue_data.get("number")
                if title:
                    candidates = self._github.search_issues(
                        event.repo_full_name, title, max_results=10
                    )
                    candidate_issues = [
                        c for c in candidates if c.get("number") != current_number
                    ]
            elif agent_name == "issue_resolution" and issue_data is not None:
                issue_number = issue_data.get("number")
                if issue_number is not None:
                    linked_pull_requests = self._github.get_linked_pull_requests(
                        event.repo_full_name, int(issue_number)
                    )
            elif agent_name in _PR_AGENT_NAMES and pr_data is not None:
                base_sha = pr_data.get("base", {}).get("sha", "")
                head_sha = pr_data.get("head", {}).get("sha", "")
                if base_sha and head_sha:
                    try:
                        changed_files = self._git.list_changed_files(base_sha, head_sha)
                        raw_diff = self._git.get_diff(base_sha, head_sha)
                        diff = raw_diff[:40_000]
                    except Exception as git_exc:
                        self._logger.log(
                            event_msg="context_fetch_error",
                            agent=agent_name,
                            error=f"git diff failed: {git_exc}",
                        )

                if agent_name == "code_quality" and changed_files:
                    py_files = [f for f in changed_files if f.endswith(".py")]
                    if py_files:
                        linter_output = _run_linters(py_files)

                if agent_name == "security" and diff:
                    secret_scan_output = _scan_secrets(diff)

                if agent_name == "test" and changed_files:
                    test_mapping = _map_tests(changed_files, str(self._git._repo_path))

        except Exception as exc:
            self._logger.log(
                event_msg="context_fetch_error",
                agent=agent_name,
                error=str(exc),
            )

        # Phase 5: retrieval (PR agents with changed files + configured retrieval layer)
        from repoheart.retrieval.layer import RetrievalContext  # local to avoid circular
        retrieval_context: RetrievalContext | None = None
        if changed_files and self._retrieval_layer is not None and self._run_budget is not None:
            query = RetrievalQuery(
                terms=_extract_terms(pr_data, diff),
                anchor_files=changed_files[:50],
                max_chars=20_000,
            )
            try:
                retrieval_context = self._retrieval_layer.retrieve(query, self._run_budget)
                self._logger.log(
                    event_msg="retrieval_complete",
                    agent=agent_name,
                    chunks=len(retrieval_context.chunks),
                    chars=retrieval_context.budget_used_chars,
                )
            except BudgetExceededError as exc:
                self._logger.log(
                    event_msg="retrieval_budget_exceeded",
                    agent=agent_name,
                    error=str(exc),
                )

        return AgentContext(
            event=event,
            config=self._config,
            provider=provider,
            issue_data=issue_data,
            pr_data=pr_data,
            diff=diff,
            changed_files=changed_files,
            fingerprint=fingerprint,
            repo_labels=repo_labels,
            candidate_issues=candidate_issues,
            linked_pull_requests=linked_pull_requests,
            linter_output=linter_output,
            secret_scan_output=secret_scan_output,
            test_mapping=test_mapping,
            retrieval_context=retrieval_context,
        )

    def _deliver_issue_comments(
        self,
        result: AgentResult,
        agent_name: str,
        event: InternalEvent,
    ) -> tuple[int, int]:
        """Format and post IssueComment objects; return (taken, escalated)."""
        entity_number = self._extract_entity_number(event)
        if entity_number is None or not self._github._token:
            return 0, 0

        # Idempotency: check if marker already present
        try:
            existing = self._github.get_issue_comments(event.repo_full_name, entity_number)
            if comment_already_posted(existing, agent_name):
                self._logger.log(
                    event_msg="issue_comment_skipped",
                    agent=agent_name,
                    reason="already_posted",
                )
                return 0, 0
        except Exception as exc:
            self._logger.log(
                event_msg="issue_comment_idempotency_error",
                agent=agent_name,
                error=str(exc),
            )

        taken = 0
        escalated = 0
        for ic in result.issue_comments:
            body = format_issue_comment(ic, agent_name)
            action = ProposedAction(
                kind=ActionKind.POST_COMMENT,
                payload={"body": body},
                reason=f"Issue comment from {agent_name}: {ic.title}",
            )
            decision = self._gate.authorize(action, agent_name)
            if decision == Decision.ALLOW:
                try:
                    self._github.post_comment(
                        event.repo_full_name, entity_number, body, decision
                    )
                    self._logger.log(
                        event_msg="issue_comment_posted",
                        agent=agent_name,
                        title=ic.title,
                    )
                    taken += 1
                except Exception as exc:
                    self._logger.log(
                        event_msg="issue_comment_error",
                        agent=agent_name,
                        error=str(exc),
                    )
            elif decision == Decision.ESCALATE:
                self._post_escalation(action, agent_name, event)
                escalated += 1
            else:
                self._logger.log(
                    event_msg="issue_comment_denied",
                    agent=agent_name,
                )
        return taken, escalated

    def _post_consolidated_review(
        self,
        pr_agent_results: dict[str, AgentResult],
        event: InternalEvent,
    ) -> tuple[int, int]:
        """Post one consolidated PR review via the GitHub PR Review API.

        Returns (taken, escalated).
        """
        entity_number = self._extract_entity_number(event)
        if entity_number is None or not self._github._token:
            self._logger.log(
                event_msg="consolidated_review_skipped",
                reason="no_token_or_entity",
            )
            return 0, 0

        # Idempotency: skip if a consolidated review already exists
        try:
            existing = self._github.get_issue_comments(event.repo_full_name, entity_number)
            if already_reviewed(existing):
                self._logger.log(
                    event_msg="consolidated_review_skipped",
                    reason="already_posted",
                )
                return 0, 0
        except Exception as exc:
            self._logger.log(
                event_msg="consolidated_review_idempotency_error",
                error=str(exc),
            )

        review_body, inline_comments = consolidate(pr_agent_results)

        # Resolve commit_id from event payload (pr_data is on context, not on result)
        commit_id = ""
        pr_payload = event.payload.get("pull_request", {})
        if isinstance(pr_payload, dict):
            commit_id = str(pr_payload.get("head", {}).get("sha", ""))

        # diff is not available here (it lives in AgentContext); skip diff-filtering
        # when inline comments are present — GitHub will reject out-of-diff lines,
        # but that is a recoverable 422 that the caller can log.
        valid_inline = inline_comments

        if commit_id:
            action = ProposedAction(
                kind=ActionKind.CREATE_PR_REVIEW,
                payload={
                    "body": review_body,
                    "inline_comments": valid_inline,
                    "commit_id": commit_id,
                },
                reason="Consolidated PR review from all PR agents",
            )
        else:
            # Fallback: plain comment when commit SHA unavailable
            action = ProposedAction(
                kind=ActionKind.POST_COMMENT,
                payload={"body": review_body},
                reason="Consolidated PR review (no commit SHA available)",
            )

        decision = self._gate.authorize(action, "pr_review_consolidator")
        if decision == Decision.ALLOW:
            try:
                self._execute_action(action, event, decision)
                self._logger.log(event_msg="consolidated_review_posted", pr=entity_number)
                return 1, 0
            except Exception as exc:
                self._logger.log(event_msg="consolidated_review_error", error=str(exc))
                return 0, 0
        elif decision == Decision.ESCALATE:
            self._post_escalation(action, "pr_review_consolidator", event)
            return 0, 1
        else:
            self._logger.log(event_msg="consolidated_review_denied")
            return 0, 0

    def _execute_action(
        self,
        action: ProposedAction,
        event: InternalEvent,
        decision: Decision,
    ) -> None:
        """Dispatch an ALLOW'd action to the appropriate GitHub/git operation."""
        entity_number = self._extract_entity_number(event)

        if action.kind == ActionKind.ADD_LABEL and entity_number is not None:
            labels = action.payload.get("labels", [])
            if isinstance(labels, list) and labels:
                self._github.add_label(event.repo_full_name, entity_number, labels, decision)

        elif action.kind == ActionKind.REMOVE_LABEL and entity_number is not None:
            pass  # Phase 3+ — no-op for now

        elif action.kind == ActionKind.POST_COMMENT and entity_number is not None:
            body = str(action.payload.get("body", ""))
            if body:
                self._github.post_comment(event.repo_full_name, entity_number, body, decision)

        elif action.kind == ActionKind.CREATE_PR_REVIEW and entity_number is not None:
            body = str(action.payload.get("body", ""))
            commit_id = str(action.payload.get("commit_id", ""))
            inline: list[dict[str, Any]] = list(action.payload.get("inline_comments", []))
            if commit_id:
                self._github.create_pr_review(
                    event.repo_full_name, entity_number, body, inline, commit_id, decision
                )
            elif body:
                # Fallback when commit SHA missing — post as plain comment
                self._github.post_comment(event.repo_full_name, entity_number, body, decision)

        else:
            self._logger.log(
                event_msg="action_unhandled",
                action_kind=action.kind.value,
                reason="not_implemented_in_phase1",
            )

    def _post_escalation(
        self,
        action: ProposedAction,
        agent_name: str,
        event: InternalEvent,
    ) -> None:
        """Post an escalation comment if a GitHub token is available."""
        entity_number = self._extract_entity_number(event)
        if entity_number is None or not self._github._token:
            self._logger.log(
                event_msg="escalation_skipped",
                agent=agent_name,
                action_kind=action.kind.value,
                reason="no_token_or_entity",
            )
            return

        risk_name = action.risk.name if action.risk else "unknown"
        body = (
            f"<!-- repoheart:escalation -->\n"
            f"**Action Requires Human Review**\n\n"
            f"RepoHeart's **{agent_name}** agent proposed an action that exceeds "
            f"the current automation level (`{self._config.automation.level}`):\n\n"
            f"- **Action:** `{action.kind.value}`\n"
            f"- **Risk:** `{risk_name}`\n"
            f"- **Reason:** {action.reason}\n\n"
            f"_RepoHeart Safety Gate — Decision: ESCALATE_"
        )
        try:
            from repoheart.safety.policy import Decision as D

            self._github.post_comment(event.repo_full_name, entity_number, body, D.ALLOW)
        except Exception as exc:
            self._logger.log(event_msg="escalation_error", error=str(exc))

    @staticmethod
    def _extract_entity_number(event: InternalEvent) -> int | None:
        """Extract the issue/PR number from the event payload, or None."""
        payload = event.payload
        if "issue" in payload and isinstance(payload["issue"], dict):
            num = payload["issue"].get("number")
            return int(num) if num is not None else None
        if "pull_request" in payload and isinstance(payload["pull_request"], dict):
            num = payload["pull_request"].get("number")
            return int(num) if num is not None else None
        return None
