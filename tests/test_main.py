"""Tests for repoheart.main."""

from __future__ import annotations

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
        code, _ = _run("--config", "opencode.yml")
    assert code == 1


def test_missing_event_file_exits_one() -> None:
    with patch.dict("os.environ", _CLEAN_ENV, clear=False):
        code, _ = _run("--event", "/nonexistent/event.json", "--config", "opencode.yml")
    assert code == 1


def test_missing_config_exits_one() -> None:
    with patch.dict("os.environ", _CLEAN_ENV, clear=False):
        code, _ = _run(
            "--event", "examples/issues.opened.json",
            "--config", "/nonexistent/opencode.yml",
        )
    assert code == 1


def test_full_pipeline_exits_zero() -> None:
    """End-to-end exit criteria: feed issues.opened.json, expect clean exit."""
    with patch.dict("os.environ", _CLEAN_ENV, clear=False):
        code, out = _run(
            "--event", "examples/issues.opened.json",
            "--config", "opencode.yml",
        )
    assert code == 0, f"Expected exit 0, got {code}\nOutput:\n{out}"
    assert "event_msg=run_complete" in out


def test_full_pipeline_logs_startup() -> None:
    with patch.dict("os.environ", _CLEAN_ENV, clear=False):
        _, out = _run("--event", "examples/issues.opened.json", "--config", "opencode.yml")
    assert "event_msg=startup" in out


def test_full_pipeline_logs_event_parsed() -> None:
    with patch.dict("os.environ", _CLEAN_ENV, clear=False):
        _, out = _run("--event", "examples/issues.opened.json", "--config", "opencode.yml")
    assert "event_msg=event_parsed" in out
    assert "routing_key=issues.opened" in out


def test_full_pipeline_logs_routed() -> None:
    with patch.dict("os.environ", _CLEAN_ENV, clear=False):
        _, out = _run("--event", "examples/issues.opened.json", "--config", "opencode.yml")
    assert "event_msg=routed" in out
    assert "issue_triage" in out


def test_full_pipeline_zero_errors() -> None:
    with patch.dict("os.environ", _CLEAN_ENV, clear=False):
        _, out = _run("--event", "examples/issues.opened.json", "--config", "opencode.yml")
    assert "errors=0" in out
