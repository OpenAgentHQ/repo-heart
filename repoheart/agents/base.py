"""The Agent contract and its declarative result types.

An agent reasons over bounded context and *declares* what it would like to do.
It never executes writes: it returns ``ProposedAction`` objects and lets the
orchestrator and Safety Gate decide what actually happens. This boundary is
what makes "no agent can escalate its own permissions" enforceable in code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from repoheart.safety.policy import ACTION_RISK, ActionKind, RiskLevel


@dataclass(frozen=True)
class Finding:
    """Status / error / diagnostic message from an agent. Not for user-facing content."""

    summary: str
    detail: str = ""
    references: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewComment:
    """Structured, actionable code-level comment for PR agents.

    Agents produce these; the orchestrator formats and delivers them via the
    GitHub PR Review API (inline where file/line are present, else in the body).
    """

    title: str
    body: str
    severity: str  # "critical" | "high" | "warning" | "info"
    file: str | None = None
    line: int | None = None
    end_line: int | None = None
    suggestion: str | None = None
    category: str | None = None  # "security" | "correctness" | "style" | "coverage"
    source: str = ""  # agent name, set by orchestrator


@dataclass(frozen=True)
class IssueComment:
    """Structured issue-level comment for issue agents.

    Agents produce these; the orchestrator formats and posts them with an
    idempotency marker via POST_COMMENT.
    """

    title: str
    body: str
    severity: str = "info"  # "critical" | "high" | "warning" | "info"
    references: list[str] = field(default_factory=list)  # e.g. ["#123"]
    source: str = ""  # agent name, set by orchestrator


@dataclass(frozen=True)
class ProposedAction:
    """A write an agent would like performed, subject to Safety Gate approval.

    ``risk`` defaults to the action kind's intrinsic risk and may only be
    raised, never lowered — an agent cannot make an action look safer than it
    is. This is validated in ``__post_init__``.
    """

    kind: ActionKind
    payload: dict[str, Any]
    reason: str
    risk: RiskLevel | None = None

    def __post_init__(self) -> None:
        intrinsic = ACTION_RISK[self.kind]
        if self.risk is None:
            object.__setattr__(self, "risk", intrinsic)
        elif self.risk < intrinsic:
            raise ValueError(
                f"{self.kind.value} cannot be proposed below its intrinsic "
                f"risk {intrinsic.name} (got {self.risk.name})"
            )


@dataclass
class AgentResult:
    """What an agent returns: typed outputs plus declarative proposed actions."""

    findings: list[Finding] = field(default_factory=list)
    review_comments: list[ReviewComment] = field(default_factory=list)
    issue_comments: list[IssueComment] = field(default_factory=list)
    proposed_actions: list[ProposedAction] = field(default_factory=list)
    confidence: float = 1.0
    needs_human_review: bool = False
    explanation: str = ""


class Agent(ABC):
    """Base class for all agents.

    Subclasses set three class attributes and implement ``run``:

      * ``name``          — stable identifier, used in logs and markers.
      * ``risk_level``    — the static ceiling this agent can never exceed.
      * ``handles_events``— event types the router may dispatch to it.
      * ``blocking``      — whether this agent's failure should fail the overall
                            run/workflow (default True, matching today's
                            behavior). Set False on agents whose findings are
                            purely informational.
    """

    name: str = "agent"
    risk_level: RiskLevel = RiskLevel.SAFE
    handles_events: list[str] = []
    blocking: bool = True

    @abstractmethod
    def run(self, context: Any) -> AgentResult:
        """Reason over context and return findings + proposed actions.

        Implementations MUST NOT call GitHub or git directly. They return a
        declarative ``AgentResult`` only.
        """
        raise NotImplementedError

    def validate_ceiling(self, result: AgentResult) -> None:
        """Assert no proposed action exceeds this agent's static risk ceiling.

        Called by the orchestrator after ``run``. A violation is a programming
        error, not a runtime condition — it means the agent tried to exceed its
        own permissions.
        """
        for action in result.proposed_actions:
            assert action.risk is not None  # set in __post_init__
            if action.risk > self.risk_level:
                raise ValueError(
                    f"agent '{self.name}' proposed {action.kind.value} at "
                    f"{action.risk.name}, exceeding its ceiling "
                    f"{self.risk_level.name}"
                )
