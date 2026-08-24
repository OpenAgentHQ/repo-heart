"""Tests for repoheart.safety.gate."""

from __future__ import annotations

import io
from typing import Any

from repoheart.agents.base import ProposedAction
from repoheart.config.schema import AutomationConfig, ProviderConfig, RepoHeartConfig
from repoheart.observability.logger import StructuredLogger
from repoheart.safety.gate import SafetyGate
from repoheart.safety.policy import ActionKind, Decision, RiskLevel


def _make_config(level: str = "assist", require_human: list[str] | None = None) -> RepoHeartConfig:
    if require_human is None:
        require_human = ["HIGH", "MEDIUM"]
    return RepoHeartConfig(
        provider=ProviderConfig(name="opencode"),
        automation=AutomationConfig(level=level, require_human_approval=require_human),
    )


def _make_gate(config: RepoHeartConfig) -> tuple[SafetyGate, io.StringIO]:
    buf = io.StringIO()

    class _CaptureLogger(StructuredLogger):
        def log(self, **kwargs: Any) -> None:
            parts = " ".join(f"{k}={v}" for k, v in kwargs.items())
            buf.write(parts + "\n")

    return SafetyGate(config=config, logger=_CaptureLogger()), buf


def _action(kind: ActionKind, risk: RiskLevel | None = None) -> ProposedAction:
    return ProposedAction(kind=kind, payload={}, reason="test", risk=risk)


# ── Hard invariants ──────────────────────────────────────────────────────────

def test_delete_branch_always_denied() -> None:
    gate, _ = _make_gate(_make_config("auto", require_human=[]))
    action = _action(ActionKind.DELETE_BRANCH)
    assert gate.authorize(action) == Decision.DENY


def test_delete_branch_denied_even_with_no_restrictions() -> None:
    gate, _ = _make_gate(_make_config("auto", require_human=[]))
    action = _action(ActionKind.DELETE_BRANCH)
    assert gate.authorize(action) == Decision.DENY


# ── SAFE actions ─────────────────────────────────────────────────────────────

def test_safe_action_allowed_in_assist() -> None:
    gate, _ = _make_gate(_make_config("assist", require_human=[]))
    assert gate.authorize(_action(ActionKind.POST_COMMENT)) == Decision.ALLOW


def test_safe_action_allowed_in_auto_safe() -> None:
    gate, _ = _make_gate(_make_config("auto-safe", require_human=[]))
    assert gate.authorize(_action(ActionKind.ADD_LABEL)) == Decision.ALLOW


def test_safe_action_allowed_in_auto() -> None:
    gate, _ = _make_gate(_make_config("auto", require_human=[]))
    assert gate.authorize(_action(ActionKind.POST_COMMENT)) == Decision.ALLOW


# ── LOW actions ───────────────────────────────────────────────────────────────

def test_low_action_escalated_in_assist() -> None:
    gate, _ = _make_gate(_make_config("assist", require_human=[]))
    assert gate.authorize(_action(ActionKind.CREATE_BRANCH)) == Decision.ESCALATE


def test_low_action_allowed_in_auto_safe() -> None:
    gate, _ = _make_gate(_make_config("auto-safe", require_human=[]))
    assert gate.authorize(_action(ActionKind.CREATE_BRANCH)) == Decision.ALLOW


def test_low_action_allowed_in_auto() -> None:
    gate, _ = _make_gate(_make_config("auto", require_human=[]))
    assert gate.authorize(_action(ActionKind.CREATE_BRANCH)) == Decision.ALLOW


# ── MEDIUM actions ────────────────────────────────────────────────────────────

def test_medium_action_escalated_in_assist() -> None:
    gate, _ = _make_gate(_make_config("assist", require_human=[]))
    assert gate.authorize(_action(ActionKind.COMMIT)) == Decision.ESCALATE


def test_medium_action_escalated_in_auto_safe() -> None:
    gate, _ = _make_gate(_make_config("auto-safe", require_human=[]))
    assert gate.authorize(_action(ActionKind.COMMIT)) == Decision.ESCALATE


def test_medium_action_allowed_in_auto_without_restriction() -> None:
    gate, _ = _make_gate(_make_config("auto", require_human=[]))
    assert gate.authorize(_action(ActionKind.COMMIT)) == Decision.ALLOW


def test_medium_action_escalated_by_require_human_in_auto() -> None:
    gate, _ = _make_gate(_make_config("auto", require_human=["MEDIUM"]))
    assert gate.authorize(_action(ActionKind.COMMIT)) == Decision.ESCALATE


# ── HIGH actions ──────────────────────────────────────────────────────────────

def test_high_action_always_escalated_in_auto() -> None:
    # HIGH risk that is not DELETE_BRANCH (hypothetical future kind)
    # We test via PUSH_BRANCH raised to HIGH
    action = ProposedAction(
        kind=ActionKind.PUSH_BRANCH,
        payload={},
        reason="test",
        risk=RiskLevel.HIGH,
    )
    gate, _ = _make_gate(_make_config("auto", require_human=[]))
    assert gate.authorize(action) == Decision.ESCALATE


# ── Logging ───────────────────────────────────────────────────────────────────

def test_every_authorize_call_produces_log_line() -> None:
    gate, buf = _make_gate(_make_config("assist", require_human=[]))
    gate.authorize(_action(ActionKind.POST_COMMENT))
    output = buf.getvalue()
    assert "event_msg=safety_gate" in output
    assert "decision=" in output


def test_log_contains_agent_name() -> None:
    gate, buf = _make_gate(_make_config("assist", require_human=[]))
    gate.authorize(_action(ActionKind.POST_COMMENT), agent_name="issue_triage")
    assert "agent=issue_triage" in buf.getvalue()
