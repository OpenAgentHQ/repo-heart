"""AgentContext — the read-only view of the world passed into every agent.

Agents receive an ``AgentContext`` and return an ``AgentResult``. They MUST
NOT store references to live clients for later side-effecting calls; all data
they need is pre-fetched and placed here by the Orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from repoheart.config.schema import RepoHeartConfig
from repoheart.events.types import InternalEvent

if TYPE_CHECKING:
    from repoheart.providers.base import Provider


@dataclass(frozen=True)
class AgentContext:
    """Everything an agent may read during a single run.

    Fields:
        event: The normalized GitHub event that triggered this agent.
        config: The validated configuration for this repository.
        provider: The AI provider for this agent's run (set in Phase 2, used
            in Phase 3). Phase 3 agents should assert ``context.provider is
            not None`` at the top of ``run()``.
        issue_data: Pre-fetched issue payload for ``issues.*`` events; else None.
        pr_data: Pre-fetched PR payload for ``pull_request.*`` events; else None.
        diff: Unified diff string for PR/push events; empty for others.
        changed_files: Relative paths of changed files; empty when not applicable.
        fingerprint: This agent's unique per-run fingerprint (for logging).
    """

    event: InternalEvent
    config: RepoHeartConfig
    provider: Provider | None = None
    issue_data: dict[str, Any] | None = None
    pr_data: dict[str, Any] | None = None
    diff: str = ""
    changed_files: list[str] = field(default_factory=list)
    fingerprint: str = ""
