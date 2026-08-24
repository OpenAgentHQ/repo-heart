"""Tests for repoheart.events.router."""

from __future__ import annotations

from repoheart.config.schema import AgentsConfig, ProviderConfig, RepoHeartConfig
from repoheart.events.router import ROUTING_TABLE, is_known_event, route
from repoheart.events.types import InternalEvent


def _make_event(routing_key: str) -> InternalEvent:
    parts = routing_key.split(".", 1)
    event_name = parts[0]
    action = parts[1] if len(parts) > 1 else ""
    return InternalEvent(
        event_name=event_name,
        action=action,
        repo_full_name="owner/repo",
        payload={},
        sender_login="alice",
    )


def _all_enabled_config() -> RepoHeartConfig:
    return RepoHeartConfig(
        provider=ProviderConfig(name="opencode"),
        agents=AgentsConfig(
            issue_triage=True,
            duplicate_detection=True,
            issue_resolution=True,
            pr_review=True,
            code_quality=True,
            security=True,
            ci_repair=True,
            conflict_resolution=True,
            test=True,
            documentation=True,
        ),
    )


def _default_config() -> RepoHeartConfig:
    return RepoHeartConfig(provider=ProviderConfig(name="opencode"))


def test_issues_opened_routes_to_three_agents() -> None:
    event = _make_event("issues.opened")
    agents = route(event, _all_enabled_config())
    assert agents == ["issue_triage", "duplicate_detection", "issue_resolution"]


def test_workflow_run_completed_routes_to_ci_repair() -> None:
    event = _make_event("workflow_run.completed")
    agents = route(event, _all_enabled_config())
    assert agents == ["ci_repair"]


def test_push_routes_to_conflict_resolution_and_documentation() -> None:
    event = _make_event("push")
    agents = route(event, _all_enabled_config())
    assert agents == ["conflict_resolution", "documentation"]


def test_unknown_event_returns_empty_list() -> None:
    event = _make_event("unknown.event")
    agents = route(event, _all_enabled_config())
    assert agents == []


def test_disabled_agent_filtered_out() -> None:
    config = RepoHeartConfig(
        provider=ProviderConfig(name="opencode"),
        agents=AgentsConfig(issue_triage=False),
    )
    event = _make_event("issues.opened")
    agents = route(event, config)
    assert "issue_triage" not in agents
    assert "duplicate_detection" in agents


def test_all_disabled_returns_empty_list() -> None:
    config = RepoHeartConfig(
        provider=ProviderConfig(name="opencode"),
        agents=AgentsConfig(
            issue_triage=False,
            duplicate_detection=False,
            issue_resolution=False,
        ),
    )
    event = _make_event("issues.opened")
    assert route(event, config) == []


def test_is_known_event_true_for_table_entry() -> None:
    event = _make_event("pull_request.opened")
    assert is_known_event(event) is True


def test_is_known_event_false_for_unknown() -> None:
    event = _make_event("unknown.thing")
    assert is_known_event(event) is False


def test_routing_table_has_all_expected_keys() -> None:
    expected = {
        "issues.opened", "issues.reopened", "issues.edited", "issues.closed",
        "issue_comment.created", "pull_request.opened", "pull_request.synchronize",
        "pull_request.reopened", "pull_request_review.submitted", "push",
        "workflow_run.completed", "check_run.completed", "release.published",
    }
    assert expected.issubset(set(ROUTING_TABLE.keys()))


def test_documentation_disabled_by_default() -> None:
    event = _make_event("release.published")
    agents = route(event, _default_config())
    assert "documentation" not in agents
