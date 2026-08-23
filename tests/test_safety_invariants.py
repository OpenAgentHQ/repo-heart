"""Safety invariant tests.

Each test here would fail if a core safety guarantee were broken. These are the
guardrails that keep future changes (human or agent) on-architecture.
"""

from __future__ import annotations

import pytest

from repoheart.agents.base import Agent, AgentResult, ProposedAction
from repoheart.safety.policy import ActionKind, RiskLevel


def test_no_merge_action_kind_exists() -> None:
    """Merge is unreachable, not merely denied: it must not exist in the enum."""
    kinds = {k.name for k in ActionKind}
    assert "MERGE" not in kinds
    assert "MERGE_PR" not in kinds
    # No force-push either.
    assert not any("FORCE" in name for name in kinds)


def test_risk_levels_are_ordered() -> None:
    assert RiskLevel.SAFE < RiskLevel.LOW < RiskLevel.MEDIUM < RiskLevel.HIGH


def test_action_cannot_be_proposed_below_intrinsic_risk() -> None:
    """An agent cannot make a MEDIUM action look SAFE."""
    with pytest.raises(ValueError):
        ProposedAction(
            kind=ActionKind.MODIFY_CODE,
            payload={},
            reason="attempted downgrade",
            risk=RiskLevel.SAFE,
        )


def test_action_defaults_to_intrinsic_risk() -> None:
    action = ProposedAction(kind=ActionKind.ADD_LABEL, payload={}, reason="triage")
    assert action.risk == RiskLevel.SAFE


class _OverreachingAgent(Agent):
    name = "overreaching"
    risk_level = RiskLevel.SAFE
    handles_events = ["issues.opened"]

    def run(self, context: object) -> AgentResult:
        return AgentResult(
            proposed_actions=[
                ProposedAction(
                    kind=ActionKind.MODIFY_CODE,  # MEDIUM, above the SAFE ceiling
                    payload={},
                    reason="should be rejected by ceiling validation",
                )
            ]
        )


def test_agent_cannot_exceed_its_risk_ceiling() -> None:
    """A SAFE-ceiling agent proposing a MEDIUM action must be rejected."""
    agent = _OverreachingAgent()
    result = agent.run(context=None)
    with pytest.raises(ValueError):
        agent.validate_ceiling(result)
