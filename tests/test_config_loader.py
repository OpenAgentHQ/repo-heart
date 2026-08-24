"""Tests for repoheart.config.loader."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from repoheart.config.loader import ConfigError, load_config


def _write_config(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "opencode.yml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


_MINIMAL_VALID = """
    repoheart:
      provider:
        name: opencode
"""


def test_loads_project_opencode_yml() -> None:
    """The real opencode.yml in the project root must parse without error."""
    config = load_config("opencode.yml")
    assert config.provider.name == "opencode"


def test_loads_minimal_valid_config(tmp_path: Path) -> None:
    p = _write_config(tmp_path, _MINIMAL_VALID)
    config = load_config(p)
    assert config.provider.name == "opencode"
    assert config.automation.level == "assist"


def test_missing_file_raises_config_error() -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config("/nonexistent/path/opencode.yml")


def test_missing_repoheart_key_raises(tmp_path: Path) -> None:
    p = _write_config(tmp_path, "something_else:\n  foo: bar\n")
    with pytest.raises(ConfigError, match="repoheart"):
        load_config(p)


def test_unknown_provider_raises(tmp_path: Path) -> None:
    p = _write_config(
        tmp_path,
        """
        repoheart:
          provider:
            name: unknown_provider
        """,
    )
    with pytest.raises(ConfigError, match="unknown_provider"):
        load_config(p)


def test_invalid_automation_level_raises(tmp_path: Path) -> None:
    p = _write_config(
        tmp_path,
        """
        repoheart:
          provider:
            name: claude
          automation:
            level: turbo
        """,
    )
    with pytest.raises(ConfigError, match="turbo"):
        load_config(p)


def test_invalid_risk_level_in_require_human_raises(tmp_path: Path) -> None:
    p = _write_config(
        tmp_path,
        """
        repoheart:
          provider:
            name: claude
          automation:
            level: auto
            require_human_approval:
              - CRITICAL
        """,
    )
    with pytest.raises(ConfigError, match="CRITICAL"):
        load_config(p)


def test_invalid_yaml_raises(tmp_path: Path) -> None:
    p = tmp_path / "opencode.yml"
    p.write_text("repoheart: {unclosed: [", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)


def test_agents_defaults_applied(tmp_path: Path) -> None:
    p = _write_config(tmp_path, _MINIMAL_VALID)
    config = load_config(p)
    assert config.agents.issue_triage is True
    assert config.agents.documentation is False


def test_agents_override(tmp_path: Path) -> None:
    p = _write_config(
        tmp_path,
        """
        repoheart:
          provider:
            name: opencode
          agents:
            issue_triage: false
            documentation: true
        """,
    )
    config = load_config(p)
    assert config.agents.issue_triage is False
    assert config.agents.documentation is True


def test_per_agent_provider_override(tmp_path: Path) -> None:
    p = _write_config(
        tmp_path,
        """
        repoheart:
          provider:
            name: opencode
          providers:
            agents:
              issue_triage: claude
        """,
    )
    config = load_config(p)
    assert config.provider_for_agent("issue_triage") == "claude"
    assert config.provider_for_agent("pr_review") == "opencode"


def test_scale_limits_override(tmp_path: Path) -> None:
    p = _write_config(
        tmp_path,
        """
        repoheart:
          provider:
            name: opencode
          scale:
            limits:
              max_llm_calls: 10
        """,
    )
    config = load_config(p)
    assert config.scale.limits.max_llm_calls == 10
    assert config.scale.limits.max_files_read == 200
