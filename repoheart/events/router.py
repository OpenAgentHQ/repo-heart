"""Deterministic event → agent routing table.

Pure Python lookup — no I/O, no config file reads, no LLM. The table is the
canonical source of truth for which agents handle which GitHub events.
"""

from __future__ import annotations

from repoheart.config.schema import RepoHeartConfig
from repoheart.events.types import InternalEvent

ROUTING_TABLE: dict[str, list[str]] = {
    "issues.opened": ["issue_triage", "duplicate_detection", "issue_resolution"],
    "issues.reopened": ["issue_triage", "duplicate_detection", "issue_resolution"],
    "issues.edited": ["issue_triage", "duplicate_detection", "issue_resolution"],
    "issues.closed": ["issue_resolution"],
    "issue_comment.created": ["issue_triage", "issue_resolution"],
    "pull_request.opened": [
        "pr_review",
        "code_quality",
        "security",
        "test",
        "conflict_resolution",
    ],
    "pull_request.synchronize": ["pr_review", "code_quality", "security", "test"],
    "pull_request.reopened": ["pr_review", "code_quality", "security", "test"],
    "pull_request_review.submitted": ["pr_review"],
    "push": ["conflict_resolution", "documentation"],
    "workflow_run.completed": ["ci_repair"],
    "check_run.completed": ["ci_repair"],
    "release.published": ["documentation"],
}


def route(event: InternalEvent, config: RepoHeartConfig) -> list[str]:
    """Return the ordered list of enabled agent names for this event.

    Args:
        event: Normalized event from ``events/context.py``.
        config: Validated config from ``config/loader.py``.

    Returns:
        Agent names in routing-table order, filtered to those enabled in config.
        Empty list if the routing key is unknown or all matching agents are disabled.
    """
    candidates = ROUTING_TABLE.get(event.routing_key, [])
    return [name for name in candidates if config.agents.is_enabled(name)]


def is_known_event(event: InternalEvent) -> bool:
    """Return True if the event's routing key exists in the routing table."""
    return event.routing_key in ROUTING_TABLE
