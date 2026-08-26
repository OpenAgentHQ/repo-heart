"""Tests for repoheart.agents.ci_repair."""

from __future__ import annotations

import json

from repoheart.agents.ci_repair import CIRepairAgent
from repoheart.config.schema import (
    AutomationConfig,
    CIConfig,
    ProviderConfig,
    RepoHeartConfig,
)
from repoheart.events.types import InternalEvent
from repoheart.orchestrator.agent_context import AgentContext
from repoheart.providers.mock import CannedResponse, MockProvider
from repoheart.safety.policy import ActionKind, RiskLevel

_WORKFLOW_RUN_DATA = {
    "id": 12345,
    "name": "ci.yml",
    "conclusion": "failure",
    "head_sha": "abc123",
}

_EVENT = InternalEvent(
    event_name="workflow_run",
    action="completed",
    repo_full_name="org/repo",
    payload={"workflow_run": _WORKFLOW_RUN_DATA},
    sender_login="github-actions",
)

_CONFIG = RepoHeartConfig(
    provider=ProviderConfig(name="mock"),
    automation=AutomationConfig(level="auto", require_human_approval=["HIGH"]),
    ci=CIConfig(watch_workflows=[], max_fix_attempts=2),
)

_SAMPLE_LOGS = """\
FAIL tests/test_config.py::test_load_missing_key
E   KeyError: 'provider'
repoheart/config/loader.py:45: KeyError
1 failed, 10 passed in 0.52s
"""

_HIGH_CONFIDENCE_RESPONSE = json.dumps({
    "root_cause": "Missing 'provider' key causes KeyError in config loader",
    "implicated_files": ["repoheart/config/loader.py"],
    "patches": [
        {
            "file": "repoheart/config/loader.py",
            "description": "Add default for missing 'provider' key",
            "search": "return config['provider']",
            "replace": "return config.get('provider', {})",
        }
    ],
    "confidence": 0.9,
    "explanation": (
        "The loader assumes 'provider' key always exists; "
        "adding .get() with default fixes the KeyError."
    ),
})

_LOW_CONFIDENCE_RESPONSE = json.dumps({
    "root_cause": "Unclear failure in test suite",
    "implicated_files": [],
    "patches": [],
    "confidence": 0.5,
    "explanation": "Cannot determine the root cause from logs alone.",
})


def _ctx(provider: MockProvider, ci_logs: str = _SAMPLE_LOGS) -> AgentContext:
    return AgentContext(
        event=_EVENT,
        config=_CONFIG,
        provider=provider,
        workflow_run_data=_WORKFLOW_RUN_DATA,
        ci_logs=ci_logs,
    )


def _valid_ctx() -> AgentContext:
    return _ctx(MockProvider(default_response=CannedResponse(_HIGH_CONFIDENCE_RESPONSE)))


# ── basic behaviour ───────────────────────────────────────────────────────────

def test_ci_repair_high_confidence_proposes_actions() -> None:
    result = CIRepairAgent().run(_valid_ctx())
    kinds = {a.kind for a in result.proposed_actions}
    assert ActionKind.CREATE_BRANCH in kinds
    assert ActionKind.MODIFY_CODE in kinds
    assert ActionKind.COMMIT in kinds
    assert ActionKind.PUSH_BRANCH in kinds


def test_ci_repair_returns_issue_comment() -> None:
    result = CIRepairAgent().run(_valid_ctx())
    assert result.issue_comments
    assert result.issue_comments[0].title


def test_ci_repair_no_force_push() -> None:
    """PUSH_BRANCH payload must never have force=True."""
    result = CIRepairAgent().run(_valid_ctx())
    for action in result.proposed_actions:
        if action.kind == ActionKind.PUSH_BRANCH:
            assert not action.payload.get("force"), "force-push is forbidden"


def test_ci_repair_fix_branch_uses_run_id() -> None:
    result = CIRepairAgent().run(_valid_ctx())
    branch_action = next(a for a in result.proposed_actions if a.kind == ActionKind.CREATE_BRANCH)
    assert "12345" in branch_action.payload["name"]


def test_ci_repair_ceiling_not_violated() -> None:
    result = CIRepairAgent().run(_valid_ctx())
    CIRepairAgent().validate_ceiling(result)


def test_ci_repair_risk_ceiling_is_medium() -> None:
    assert CIRepairAgent.risk_level == RiskLevel.MEDIUM


# ── low confidence escalation ─────────────────────────────────────────────────

def test_ci_repair_low_confidence_escalates() -> None:
    provider = MockProvider(default_response=CannedResponse(_LOW_CONFIDENCE_RESPONSE))
    result = CIRepairAgent().run(_ctx(provider))
    assert result.needs_human_review
    kinds = {a.kind for a in result.proposed_actions}
    assert ActionKind.MODIFY_CODE not in kinds


def test_ci_repair_low_confidence_still_has_comment() -> None:
    provider = MockProvider(default_response=CannedResponse(_LOW_CONFIDENCE_RESPONSE))
    result = CIRepairAgent().run(_ctx(provider))
    assert result.issue_comments
    assert "manual" in result.issue_comments[0].body.lower()


# ── guard rails ──────────────────────────────────────────────────────────────

def test_ci_repair_empty_logs_returns_finding() -> None:
    result = CIRepairAgent().run(_ctx(MockProvider(), ci_logs=""))
    assert result.findings
    assert "No CI logs" in result.findings[0].summary
    assert not result.proposed_actions


def test_ci_repair_no_provider_returns_finding() -> None:
    ctx = AgentContext(
        event=_EVENT,
        config=_CONFIG,
        provider=None,
        workflow_run_data=_WORKFLOW_RUN_DATA,
        ci_logs=_SAMPLE_LOGS,
    )
    result = CIRepairAgent().run(ctx)
    assert result.findings
    assert "No provider" in result.findings[0].summary


def test_ci_repair_provider_error_returns_finding() -> None:
    result = CIRepairAgent().run(_ctx(MockProvider(raise_on_complete=RuntimeError("timeout"))))
    assert result.findings
    assert "Provider error" in result.findings[0].summary


def test_ci_repair_bad_json_treated_as_low_confidence() -> None:
    provider = MockProvider(default_response=CannedResponse("not json"))
    result = CIRepairAgent().run(_ctx(provider))
    # confidence defaults to 0.0 → needs_human_review
    assert result.needs_human_review
    assert not any(a.kind == ActionKind.MODIFY_CODE for a in result.proposed_actions)


def test_ci_repair_watch_workflows_filter() -> None:
    config = RepoHeartConfig(
        provider=ProviderConfig(name="mock"),
        automation=AutomationConfig(level="auto"),
        ci=CIConfig(watch_workflows=["deploy.yml"]),
    )
    ctx = AgentContext(
        event=_EVENT,
        config=config,
        provider=MockProvider(default_response=CannedResponse(_HIGH_CONFIDENCE_RESPONSE)),
        workflow_run_data=_WORKFLOW_RUN_DATA,  # name="ci.yml", not in watch list
        ci_logs=_SAMPLE_LOGS,
    )
    result = CIRepairAgent().run(ctx)
    assert result.findings
    assert "not in watch_workflows" in result.findings[0].summary


def test_ci_repair_non_failure_conclusion() -> None:
    wr_data = {**_WORKFLOW_RUN_DATA, "conclusion": "success"}
    ctx = AgentContext(
        event=_EVENT,
        config=_CONFIG,
        provider=MockProvider(default_response=CannedResponse(_HIGH_CONFIDENCE_RESPONSE)),
        workflow_run_data=wr_data,
        ci_logs=_SAMPLE_LOGS,
    )
    result = CIRepairAgent().run(ctx)
    assert result.findings
    assert "not a failure" in result.findings[0].summary


def test_ci_repair_handles_events() -> None:
    agent = CIRepairAgent()
    assert "workflow_run.completed" in agent.handles_events
    assert "check_run.completed" in agent.handles_events


def test_ci_repair_no_delete_branch_proposed() -> None:
    """DELETE_BRANCH must never appear in CI repair output."""
    result = CIRepairAgent().run(_valid_ctx())
    kinds = {a.kind for a in result.proposed_actions}
    assert ActionKind.DELETE_BRANCH not in kinds
