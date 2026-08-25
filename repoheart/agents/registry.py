"""Agent registry: maps agent names to their implementing classes.

In Phase 1 all entries point to ``NoOpAgent``. Real implementations replace
individual entries as each phase is completed. The orchestrator uses this
registry exclusively — never imports agent classes directly.
"""

from __future__ import annotations

from repoheart.agents.base import Agent
from repoheart.agents.duplicate_detection import DuplicateDetectionAgent
from repoheart.agents.issue_resolution import IssueResolutionAgent
from repoheart.agents.issue_triage import IssueTriageAgent
from repoheart.agents.noop import NoOpAgent

AGENT_REGISTRY: dict[str, type[Agent]] = {
    "issue_triage": IssueTriageAgent,
    "duplicate_detection": DuplicateDetectionAgent,
    "issue_resolution": IssueResolutionAgent,
    "pr_review": NoOpAgent,
    "code_quality": NoOpAgent,
    "security": NoOpAgent,
    "ci_repair": NoOpAgent,
    "conflict_resolution": NoOpAgent,
    "test": NoOpAgent,
    "documentation": NoOpAgent,
}
