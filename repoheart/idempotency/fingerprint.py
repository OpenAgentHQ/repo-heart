"""Deterministic event fingerprinting for idempotency without a database.

Fingerprints are SHA-256 hashes over a canonical string that encodes the
event, entity, and (optionally) the agent. Storing these hashes as GitHub
comment markers, labels, or commit trailers lets us detect and skip duplicate
runs without any external state store.
"""

from __future__ import annotations

import hashlib
from typing import Any

from repoheart.events.types import InternalEvent


def compute_fingerprint(
    event_name: str,
    action: str,
    repo_full_name: str,
    entity_id: str | int,
    agent_name: str = "",
) -> str:
    """Return a 64-char lowercase hex SHA-256 fingerprint.

    The canonical form is:
        ``"{event_name}.{action}:{repo_full_name}:{entity_id}:{agent_name}"``

    When ``agent_name`` is empty this is an event-level fingerprint (used for
    pre-routing idempotency). When set, it is a per-agent fingerprint.
    """
    canonical = f"{event_name}.{action}:{repo_full_name}:{entity_id}:{agent_name}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprint_for_event(event: InternalEvent, agent_name: str = "") -> str:
    """Convenience wrapper that extracts ``entity_id`` from the event payload.

    Entity ID resolution order:
    1. ``payload["issue"]["number"]``       — issues.* events
    2. ``payload["pull_request"]["number"]``— pull_request.* events
    3. ``payload["workflow_run"]["id"]``    — workflow_run.* events
    4. ``payload["release"]["id"]``         — release.* events
    5. ``payload.get("after", "")``         — push events (head SHA)
    6. ``""``                               — fallback (still deterministic)
    """
    payload: dict[str, Any] = event.payload
    entity_id: str | int = ""

    if "issue" in payload and isinstance(payload["issue"], dict):
        entity_id = payload["issue"].get("number", "")
    elif "pull_request" in payload and isinstance(payload["pull_request"], dict):
        entity_id = payload["pull_request"].get("number", "")
    elif "workflow_run" in payload and isinstance(payload["workflow_run"], dict):
        entity_id = payload["workflow_run"].get("id", "")
    elif "release" in payload and isinstance(payload["release"], dict):
        entity_id = payload["release"].get("id", "")
    elif "after" in payload:
        entity_id = str(payload.get("after", ""))

    return compute_fingerprint(
        event_name=event.event_name,
        action=event.action,
        repo_full_name=event.repo_full_name,
        entity_id=entity_id,
        agent_name=agent_name,
    )
