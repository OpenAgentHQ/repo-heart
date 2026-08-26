"""Tests for repoheart.cli.actions_report — the GitHub Actions plan/result JSON builders."""

from __future__ import annotations

import json

from repoheart.agents.registry import AGENT_REGISTRY
from repoheart.cli.actions_report import (
    agent_label,
    build_plan,
    build_result,
    write_plan,
    write_result,
)
from repoheart.config.schema import AgentsConfig, ProviderConfig, RepoHeartConfig
from repoheart.events.types import InternalEvent


def _event(routing_key: str) -> InternalEvent:
    event_name, _, action = routing_key.partition(".")
    return InternalEvent(
        event_name=event_name,
        action=action,
        repo_full_name="owner/repo",
        payload={},
        sender_login="alice",
    )


def test_agent_label_title_cases_registry_key() -> None:
    assert agent_label("issue_triage") == "Issue Triage"
    assert agent_label("ci_repair") == "CI Repair"
    assert agent_label("pr_review") == "PR Review"


def test_build_plan_includes_every_registered_agent() -> None:
    config = RepoHeartConfig(provider=ProviderConfig(name="opencode"))
    plan = build_plan(_event("issues.opened"), config)
    ids = {a["id"] for a in plan["agents"]}
    assert ids == set(AGENT_REGISTRY.keys())


def test_build_plan_marks_routed_agents_activated() -> None:
    config = RepoHeartConfig(
        provider=ProviderConfig(name="opencode"),
        agents=AgentsConfig(issue_triage=True, duplicate_detection=True, issue_resolution=True),
    )
    plan = build_plan(_event("issues.opened"), config)
    by_id = {a["id"]: a for a in plan["agents"]}
    assert by_id["issue_triage"]["activated"] is True
    assert by_id["pr_review"]["activated"] is False
    assert plan["agent_ids"] == sorted(
        ["issue_triage", "duplicate_detection", "issue_resolution"]
    )


def test_build_plan_never_includes_secrets() -> None:
    config = RepoHeartConfig(provider=ProviderConfig(name="opencode", model="secret-model-id"))
    plan = build_plan(_event("push"), config)
    dumped = json.dumps(plan)
    assert "API_KEY" not in dumped
    assert "token" not in dumped.lower()


def test_write_plan_writes_json_into_workspace(tmp_path) -> None:
    config = RepoHeartConfig(provider=ProviderConfig(name="opencode"))
    plan = build_plan(_event("push"), config)
    out_path = write_plan(plan, str(tmp_path))
    assert out_path == tmp_path / ".repoheart" / "plan.json"
    assert json.loads(out_path.read_text())["event"] == "push"


def test_write_result_writes_json_into_workspace(tmp_path) -> None:
    result = build_result(
        agent_name="issue_triage",
        activated=True,
        status="ok",
        stage="complete",
        error="",
        findings=1,
        actions=0,
        provider="opencode",
        model="",
        blocking=True,
    )
    out_path = write_result(result, str(tmp_path))
    assert out_path == tmp_path / ".repoheart" / "result-issue_triage.json"
    loaded = json.loads(out_path.read_text())
    assert loaded["status"] == "ok"
    assert loaded["label"] == "Issue Triage"
