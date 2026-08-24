"""Tests for repoheart.events.types."""

from __future__ import annotations

import pytest

from repoheart.events.types import InternalEvent


def _make_event(**kwargs: object) -> InternalEvent:
    defaults: dict[str, object] = {
        "event_name": "issues",
        "action": "opened",
        "repo_full_name": "owner/repo",
        "payload": {},
        "sender_login": "alice",
    }
    defaults.update(kwargs)
    return InternalEvent(**defaults)  # type: ignore[arg-type]


def test_routing_key_with_action() -> None:
    event = _make_event(event_name="issues", action="opened")
    assert event.routing_key == "issues.opened"


def test_routing_key_without_action() -> None:
    event = _make_event(event_name="push", action="")
    assert event.routing_key == "push"


def test_routing_key_pull_request_synchronize() -> None:
    event = _make_event(event_name="pull_request", action="synchronize")
    assert event.routing_key == "pull_request.synchronize"


def test_frozen_instance_raises_on_mutation() -> None:
    event = _make_event()
    with pytest.raises((AttributeError, TypeError)):
        event.action = "closed"  # type: ignore[misc]


def test_all_fields_accessible() -> None:
    payload = {"issue": {"number": 1}}
    event = InternalEvent(
        event_name="issues",
        action="opened",
        repo_full_name="org/repo",
        payload=payload,
        sender_login="bob",
    )
    assert event.event_name == "issues"
    assert event.action == "opened"
    assert event.repo_full_name == "org/repo"
    assert event.payload == payload
    assert event.sender_login == "bob"
