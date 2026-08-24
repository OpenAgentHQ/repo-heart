"""No-op agent placeholder used in Phase 1.

In Phase 1 all agent slots in the registry point to ``NoOpAgent``. It
proposes no actions and makes no LLM calls, allowing the full pipeline to
be exercised end-to-end before any real agents exist.
"""

from __future__ import annotations

from repoheart.agents.base import Agent, AgentResult
from repoheart.safety.policy import RiskLevel


class NoOpAgent(Agent):
    """Phase 1 placeholder: returns an empty AgentResult, no LLM calls."""

    name: str = "noop"
    risk_level: RiskLevel = RiskLevel.SAFE
    handles_events: list[str] = ["*"]

    def run(self, context: object) -> AgentResult:
        return AgentResult(explanation="no-op: Phase 1 placeholder")
