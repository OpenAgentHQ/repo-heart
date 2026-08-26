"""Tests for repoheart.main."""

from __future__ import annotations

import json
from io import StringIO
from unittest.mock import patch

from repoheart.main import main

# Env vars that GitHub Actions sets and that can interfere with tests.
_CLEAN_ENV = {"GITHUB_TOKEN": "", "GITHUB_EVENT_NAME": "", "GITHUB_EVENT_PATH": ""}


def _run(*args: str) -> tuple[int, str]:
    buf = StringIO()
    with patch("sys.stdout", buf):
        code = main(list(args))
    return code, buf.getvalue()


def test_version_exits_zero() -> None:
    code, out = _run("--version")
    assert code == 0
    assert out.strip()


def test_no_event_exits_one() -> None:
    with patch.dict("os.environ", _CLEAN_ENV, clear=False):
        code, _ = _run("--config", "repoheart.yml")
    assert code == 1


def test_missing_event_file_exits_one() -> None:
    with patch.dict("os.environ", _CLEAN_ENV, clear=False):
        code, _ = _run("--event", "/nonexistent/event.json", "--config", "repoheart.yml")
    assert code == 1


def test_missing_config_exits_one() -> None:
    with patch.dict("os.environ", _CLEAN_ENV, clear=False):
        code, _ = _run(
            "--event", "examples/issues.opened.json",
            "--config", "/nonexistent/repoheart.yml",
        )
    assert code == 1


def test_full_pipeline_exits_zero() -> None:
    """End-to-end exit criteria: feed issues.opened.json, expect clean exit."""
    with patch.dict("os.environ", _CLEAN_ENV, clear=False):
        code, out = _run(
            "--event", "examples/issues.opened.json",
            "--config", "repoheart.yml",
        )
    assert code == 0, f"Expected exit 0, got {code}\nOutput:\n{out}"
    assert "event_msg=run_complete" in out


def test_full_pipeline_logs_startup() -> None:
    with patch.dict("os.environ", _CLEAN_ENV, clear=False):
        _, out = _run("--event", "examples/issues.opened.json", "--config", "repoheart.yml")
    assert "event_msg=startup" in out


def test_full_pipeline_logs_event_parsed() -> None:
    with patch.dict("os.environ", _CLEAN_ENV, clear=False):
        _, out = _run("--event", "examples/issues.opened.json", "--config", "repoheart.yml")
    assert "event_msg=event_parsed" in out
    assert "routing_key=issues.opened" in out


def test_full_pipeline_logs_routed() -> None:
    with patch.dict("os.environ", _CLEAN_ENV, clear=False):
        _, out = _run("--event", "examples/issues.opened.json", "--config", "repoheart.yml")
    assert "event_msg=routed" in out
    assert "issue_triage" in out


def test_full_pipeline_zero_errors() -> None:
    with patch.dict("os.environ", _CLEAN_ENV, clear=False):
        _, out = _run("--event", "examples/issues.opened.json", "--config", "repoheart.yml")
    assert "errors=0" in out


# --- plan subcommand ---


def test_plan_lists_activated_and_skipped_agents(tmp_path) -> None:
    with patch.dict("os.environ", {**_CLEAN_ENV, "GITHUB_WORKSPACE": str(tmp_path)}):
        code, out = _run(
            "plan", "--event", "examples/issues.opened.json", "--config", "repoheart.yml"
        )
    assert code == 0
    plan = json.loads(out.strip().splitlines()[0])
    assert plan["event"] == "issues.opened"
    by_id = {a["id"]: a for a in plan["agents"]}
    assert by_id["issue_triage"]["activated"] is True
    assert by_id["pr_review"]["activated"] is False


def test_plan_writes_result_file_into_workspace(tmp_path) -> None:
    with patch.dict("os.environ", {**_CLEAN_ENV, "GITHUB_WORKSPACE": str(tmp_path)}):
        code, _ = _run(
            "plan", "--event", "examples/issues.opened.json", "--config", "repoheart.yml"
        )
    assert code == 0
    assert (tmp_path / ".repoheart" / "plan.json").is_file()


def test_plan_missing_event_exits_one() -> None:
    with patch.dict("os.environ", _CLEAN_ENV, clear=False):
        code, _ = _run("plan", "--config", "repoheart.yml")
    assert code == 1


# --- run --agent ---


def test_run_agent_selects_only_that_agent(tmp_path) -> None:
    with patch.dict("os.environ", {**_CLEAN_ENV, "GITHUB_WORKSPACE": str(tmp_path)}):
        code, out = _run(
            "run",
            "--event", "examples/issues.opened.json",
            "--config", "repoheart.yml",
            "--agent", "issue_triage",
        )
    assert code == 0, out
    assert "event_msg=routed agents=issue_triage" in out
    result = json.loads((tmp_path / ".repoheart" / "result-issue_triage.json").read_text())
    assert result["status"] == "ok"
    assert result["activated"] is True


def test_run_agent_not_activated_is_skipped_not_failed(tmp_path) -> None:
    with patch.dict("os.environ", {**_CLEAN_ENV, "GITHUB_WORKSPACE": str(tmp_path)}):
        code, out = _run(
            "run",
            "--event", "examples/issues.opened.json",
            "--config", "repoheart.yml",
            "--agent", "pr_review",
        )
    assert code == 0, out
    result = json.loads((tmp_path / ".repoheart" / "result-pr_review.json").read_text())
    assert result["status"] == "skipped"


def test_run_unknown_agent_exits_one() -> None:
    with patch.dict("os.environ", _CLEAN_ENV, clear=False):
        code, _ = _run(
            "run",
            "--event", "examples/issues.opened.json",
            "--config", "repoheart.yml",
            "--agent", "not_a_real_agent",
        )
    assert code == 1


def test_run_without_agent_flag_behaves_as_before() -> None:
    with patch.dict("os.environ", _CLEAN_ENV, clear=False):
        code, out = _run(
            "run", "--event", "examples/issues.opened.json", "--config", "repoheart.yml"
        )
    assert code == 0
    assert "issue_triage" in out
    assert "duplicate_detection" in out
