"""Typed, normalized event data passed through the pipeline.

The sole source of truth for what a GitHub event looks like inside RepoHeart.
All downstream modules work against ``InternalEvent``; the raw JSON payload
stays in ``.payload`` for agent use but is never read directly outside of
``events/context.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InternalEvent:
    """Normalized representation of a GitHub webhook event."""

    event_name: str
    action: str
    repo_full_name: str
    payload: dict[str, Any]
    sender_login: str

    @property
    def routing_key(self) -> str:
        """Composite key used by the router (e.g. ``"issues.opened"``).

        For push events where ``action`` is empty, returns just ``event_name``.
        """
        if self.action:
            return f"{self.event_name}.{self.action}"
        return self.event_name
