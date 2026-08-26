"""Load and normalize a GitHub event payload into an InternalEvent.

This is the only module that reads ``GITHUB_EVENT_PATH`` / ``GITHUB_EVENT_NAME``
from the environment. Everything downstream works against the typed
``InternalEvent``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from repoheart.events.types import InternalEvent


class EventLoadError(RuntimeError):
    """Raised when the event file is missing, unreadable, or invalid JSON."""


def load_event(event_path: str | Path, event_name: str) -> InternalEvent:
    """Read a GitHub event JSON file and return a normalized InternalEvent.

    Args:
        event_path: Path to the JSON payload (from ``GITHUB_EVENT_PATH`` or
            the ``--event`` CLI argument).
        event_name: GitHub event name (from ``GITHUB_EVENT_NAME`` env var or
            inferred via ``infer_event_name``).

    Raises:
        EventLoadError: if the file is missing, unreadable, or invalid JSON,
            or if the payload is missing required fields.
    """
    resolved = Path(event_path)
    if not resolved.is_file():
        raise EventLoadError(f"Event file not found: {resolved}")

    try:
        payload: dict[str, Any] = json.loads(resolved.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise EventLoadError(f"Failed to read event file {resolved}: {exc}") from exc

    if not isinstance(payload, dict):
        raise EventLoadError(f"Event payload in {resolved} must be a JSON object")

    repo = payload.get("repository", {})
    if not isinstance(repo, dict) or not repo.get("full_name"):
        raise EventLoadError(
            f"Event payload missing required field 'repository.full_name' in {resolved}"
        )

    action = str(payload.get("action", ""))
    repo_full_name = str(repo["full_name"])
    sender = payload.get("sender", {})
    sender_login = str(sender.get("login", "")) if isinstance(sender, dict) else ""

    return InternalEvent(
        event_name=event_name,
        action=action,
        repo_full_name=repo_full_name,
        payload=payload,
        sender_login=sender_login,
    )


def infer_event_name(payload: dict[str, Any]) -> str:
    """Infer the GitHub event name from payload structure.

    Used only for local/test runs where ``GITHUB_EVENT_NAME`` is not set.
    The heuristic matches the most common payload shapes.
    """
    if "comment" in payload and "issue" in payload:
        return "issue_comment"
    if "issue" in payload:
        return "issues"
    if "pull_request" in payload:
        return "pull_request"
    if "workflow_run" in payload:
        return "workflow_run"
    if "release" in payload:
        return "release"
    if "check_run" in payload:
        return "check_run"
    if "review" in payload:
        return "pull_request_review"
    return "push"
