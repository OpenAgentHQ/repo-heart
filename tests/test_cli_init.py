"""Tests for repoheart init CLI command."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import patch

from repoheart.main import main


def _run(*args: str) -> tuple[int, str]:
    buf = StringIO()
    with patch("sys.stdout", buf):
        code = main(list(args))
    return code, buf.getvalue()


def test_init_writes_both_files(tmp_path: Path) -> None:
    code, _ = _run("init", "--yes", "--output-dir", str(tmp_path))
    assert code == 0
    config = tmp_path / "repoheart.yml"
    workflow = tmp_path / ".github" / "workflows" / "repoheart.yml"
    assert config.exists()
    assert workflow.exists()
    config_text = config.read_text(encoding="utf-8")
    assert "repoheart:" in config_text
    assert "provider:" in config_text
    assert "agents:" in config_text
    workflow_text = workflow.read_text(encoding="utf-8")
    assert "OpenAgentHQ/repoheart@main" in workflow_text
    assert "GITHUB_TOKEN" in workflow_text


def test_init_fails_without_force_when_files_exist(tmp_path: Path) -> None:
    (tmp_path / "repoheart.yml").write_text("existing", encoding="utf-8")
    code, _ = _run("init", "--yes", "--output-dir", str(tmp_path))
    assert code == 1


def test_init_with_force_overwrites(tmp_path: Path) -> None:
    (tmp_path / "repoheart.yml").write_text("old", encoding="utf-8")
    workflows_dir = tmp_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "repoheart.yml").write_text("old", encoding="utf-8")
    code, _ = _run("init", "--yes", "--force", "--output-dir", str(tmp_path))
    assert code == 0
    assert (tmp_path / "repoheart.yml").read_text(encoding="utf-8") != "old"


def test_init_with_provider_and_model_flags(tmp_path: Path) -> None:
    code, _ = _run(
        "init",
        "--provider", "claude",
        "--model", "claude-opus-4-8",
        "--yes",
        "--output-dir", str(tmp_path),
    )
    assert code == 0
    config_text = (tmp_path / "repoheart.yml").read_text(encoding="utf-8")
    assert "name: claude" in config_text
    assert "model: claude-opus-4-8" in config_text


def test_version_flag_unchanged() -> None:
    code, out = _run("--version")
    assert code == 0
    assert out.strip()


def test_run_subcommand_missing_event_exits_one() -> None:
    from unittest.mock import patch as _patch
    _CLEAN = {"GITHUB_TOKEN": "", "GITHUB_EVENT_NAME": "", "GITHUB_EVENT_PATH": ""}
    with _patch.dict("os.environ", _CLEAN, clear=False):
        code, _ = _run("run", "--config", "repoheart.yml")
    assert code == 1
