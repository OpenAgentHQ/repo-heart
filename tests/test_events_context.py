"""Tests for repoheart.events.context."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repoheart.events.context import EventLoadError, infer_event_name, load_event


def test_load_sample_issues_opened_json() -> None:
    event = load_event("examples/issues.opened.json", "issues")
    assert event.event_name == "issues"
    assert event.action == "opened"
    assert event.repo_full_name == "example-org/example-repo"
    assert event.sender_login == "example-contributor"
    assert event.routing_key == "issues.opened"


def test_load_event_missing_file_raises() -> None:
    with pytest.raises(EventLoadError, match="not found"):
        load_event("/nonexistent/event.json", "issues")


def test_load_event_malformed_json_raises(tmp_path: Path) -> None:
    p = tmp_path / "event.json"
    p.write_text("{broken json", encoding="utf-8")
    with pytest.raises(EventLoadError):
        load_event(p, "issues")


def test_load_event_missing_repository_full_name_raises(tmp_path: Path) -> None:
    p = tmp_path / "event.json"
    p.write_text(json.dumps({"action": "opened", "repository": {}}), encoding="utf-8")
    with pytest.raises(EventLoadError, match="repository.full_name"):
        load_event(p, "issues")


def test_load_event_missing_repository_key_raises(tmp_path: Path) -> None:
    p = tmp_path / "event.json"
    p.write_text(json.dumps({"action": "opened"}), encoding="utf-8")
    with pytest.raises(EventLoadError, match="repository.full_name"):
        load_event(p, "push")


def test_load_event_no_action_defaults_to_empty_string(tmp_path: Path) -> None:
    p = tmp_path / "event.json"
    payload = {"repository": {"full_name": "org/repo"}}
    p.write_text(json.dumps(payload), encoding="utf-8")
    event = load_event(p, "push")
    assert event.action == ""
    assert event.routing_key == "push"


def test_load_event_no_sender_defaults_to_empty_string(tmp_path: Path) -> None:
    p = tmp_path / "event.json"
    payload = {"action": "opened", "repository": {"full_name": "org/repo"}}
    p.write_text(json.dumps(payload), encoding="utf-8")
    event = load_event(p, "issues")
    assert event.sender_login == ""


class TestInferEventName:
    def test_infers_issues_from_issue_key(self) -> None:
        assert infer_event_name({"issue": {}, "action": "opened"}) == "issues"

    def test_infers_pull_request(self) -> None:
        assert infer_event_name({"pull_request": {}, "action": "opened"}) == "pull_request"

    def test_infers_workflow_run(self) -> None:
        assert infer_event_name({"workflow_run": {}, "action": "completed"}) == "workflow_run"

    def test_infers_release(self) -> None:
        assert infer_event_name({"release": {}, "action": "published"}) == "release"

    def test_infers_check_run(self) -> None:
        assert infer_event_name({"check_run": {}, "action": "completed"}) == "check_run"

    def test_infers_push_as_fallback(self) -> None:
        assert infer_event_name({"commits": [], "ref": "refs/heads/main"}) == "push"

    def test_sample_issues_payload_inferred_correctly(self) -> None:
        payload = json.loads(Path("examples/issues.opened.json").read_text(encoding="utf-8"))
        assert infer_event_name(payload) == "issues"
