"""Agent registry: maps agent names to their implementing classes.

In Phase 1 all entries point to ``NoOpAgent``. Real implementations replace
individual entries as each phase is completed. The orchestrator uses this
registry exclusively — never imports agent classes directly.
"""

from __future__ import annotations

from repoheart.agents.base import Agent
from repoheart.agents.ci_repair import CIRepairAgent
from repoheart.agents.code_quality import CodeQualityAgent
from repoheart.agents.conflict_resolution import ConflictResolutionAgent
from repoheart.agents.duplicate_detection import DuplicateDetectionAgent
from repoheart.agents.issue_resolution import IssueResolutionAgent
from repoheart.agents.issue_triage import IssueTriageAgent
from repoheart.agents.noop import NoOpAgent
from repoheart.agents.pr_review import PRReviewAgent
from repoheart.agents.security import SecurityAgent
from repoheart.agents.test_agent import TestCoverageAgent

AGENT_REGISTRY: dict[str, type[Agent]] = {
    "issue_triage": IssueTriageAgent,
    "duplicate_detection": DuplicateDetectionAgent,
    "issue_resolution": IssueResolutionAgent,
    "pr_review": PRReviewAgent,
    "code_quality": CodeQualityAgent,
    "security": SecurityAgent,
    "ci_repair": CIRepairAgent,
    "conflict_resolution": ConflictResolutionAgent,
    "test": TestCoverageAgent,
    "documentation": NoOpAgent,
}
