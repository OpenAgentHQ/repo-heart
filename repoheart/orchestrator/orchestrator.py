"""Orchestrator — sequences agent execution for a single event.

The Orchestrator is the only component that calls agents, feeds results to the
Safety Gate, and dispatches allowed actions. It catches per-agent exceptions so
one failing agent never aborts the entire run.
"""

from __future__ import annotations

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
from repoheart.providers.base import Provider
from repoheart.safety.gate import SafetyGate
from repoheart.safety.policy import ActionKind, Decision


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
    ) -> None:
        self._config = config
        self._github = github_client
        self._git = git_repo
        self._gate = safety_gate
        self._markers = markers
        self._logger = logger
        self._provider_factory = provider_factory

    def run(self, event: InternalEvent, agent_names: list[str]) -> RunSummary:
        """Execute the pipeline for a routed event.

        For each agent:
        1. Check idempotency — skip if already processed.
        2. Build AgentContext (pre-fetch relevant GitHub data).
        3. Instantiate agent from registry.
        4. Call agent.run(context) — catch exceptions, log, continue.
        5. Validate agent's risk ceiling.
        6. For each proposed action: gate → execute / escalate / deny.
        """
        summary = RunSummary(event=event)

        for agent_name in agent_names:
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

            # 6. Gate and dispatch
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

        provider: Provider | None = None
        if self._provider_factory is not None:
            provider = self._provider_factory(agent_name)

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
        except Exception as exc:
            self._logger.log(
                event_msg="context_fetch_error",
                agent=agent_name,
                error=str(exc),
            )

        return AgentContext(
            event=event,
            config=self._config,
            provider=provider,
            issue_data=issue_data,
            pr_data=pr_data,
            fingerprint=fingerprint,
            repo_labels=repo_labels,
            candidate_issues=candidate_issues,
            linked_pull_requests=linked_pull_requests,
        )

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
