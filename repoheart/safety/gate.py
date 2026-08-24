"""Safety Gate — the mandatory checkpoint for every write.

Every proposed action must pass through ``SafetyGate.authorize()`` before it
can be executed. Decisions are logged unconditionally so the Actions run log
provides a complete audit trail.
"""

from __future__ import annotations

from repoheart.agents.base import ProposedAction
from repoheart.config.schema import RepoHeartConfig
from repoheart.observability.logger import StructuredLogger
from repoheart.safety.policy import ActionKind, Decision, RiskLevel

# Automation level → the highest risk that may be auto-approved.
_LEVEL_CEILING: dict[str, RiskLevel] = {
    "assist": RiskLevel.SAFE,
    "auto-safe": RiskLevel.LOW,
    "auto": RiskLevel.MEDIUM,
}

# Actions that are always DENY in the MVP regardless of config.
_ALWAYS_DENY: frozenset[ActionKind] = frozenset({ActionKind.DELETE_BRANCH})


class SafetyGate:
    """Authorizes proposed actions against config policy and hard invariants.

    Instantiated once per run; each call to ``authorize`` is independent and
    produces a log line.
    """

    def __init__(self, config: RepoHeartConfig, logger: StructuredLogger) -> None:
        self._config = config
        self._logger = logger

    def authorize(self, action: ProposedAction, agent_name: str = "") -> Decision:
        """Return the decision for a single proposed action.

        Evaluation order:
        1. Hard invariants — always DENY, no config can override.
        2. ``require_human_approval`` — ESCALATE if action.risk.name is listed.
        3. Automation level ceiling — ESCALATE if risk exceeds the configured max.
        4. HIGH risk — always ESCALATE regardless of automation level.
        5. Otherwise → ALLOW.
        """
        assert action.risk is not None  # set by ProposedAction.__post_init__
        risk: RiskLevel = action.risk

        # 1. Hard invariants
        if action.kind in _ALWAYS_DENY:
            decision = Decision.DENY
            reason = f"action_kind={action.kind.value} is always denied in MVP"
            self._log(agent_name, action, decision, reason)
            return decision

        # 2. require_human_approval
        if risk.name in self._config.automation.require_human_approval:
            decision = Decision.ESCALATE
            reason = f"risk={risk.name} is in require_human_approval"
            self._log(agent_name, action, decision, reason)
            return decision

        # 3 & 4. Automation level ceiling (HIGH always escalates)
        ceiling = _LEVEL_CEILING.get(self._config.automation.level, RiskLevel.SAFE)
        if risk > ceiling or risk == RiskLevel.HIGH:
            decision = Decision.ESCALATE
            reason = (
                f"risk={risk.name} exceeds automation_level={self._config.automation.level}"
            )
            self._log(agent_name, action, decision, reason)
            return decision

        decision = Decision.ALLOW
        self._log(agent_name, action, decision, "within_policy")
        return decision

    def _log(
        self,
        agent_name: str,
        action: ProposedAction,
        decision: Decision,
        reason: str,
    ) -> None:
        self._logger.log(
            event_msg="safety_gate",
            agent=agent_name or "unknown",
            action_kind=action.kind.value,
            risk=action.risk.name if action.risk else "none",
            decision=decision.value,
            reason=reason,
        )
