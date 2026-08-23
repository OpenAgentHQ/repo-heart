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
    """A single observation an agent made about the repository."""

    summary: str
    detail: str = ""
    references: list[str] = field(default_factory=list)


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
    """What an agent returns: findings plus declarative proposed actions."""

    findings: list[Finding] = field(default_factory=list)
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
    """

    name: str = "agent"
    risk_level: RiskLevel = RiskLevel.SAFE
    handles_events: list[str] = []

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
