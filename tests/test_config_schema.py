"""Tests for repoheart.config.schema."""

from __future__ import annotations

from repoheart.config.schema import (
    AgentsConfig,
    AutomationConfig,
    LimitsConfig,
    ProviderConfig,
    ProvidersConfig,
    RepoHeartConfig,
)


def _default_config(**kwargs: object) -> RepoHeartConfig:
    base: dict[str, object] = {"provider": ProviderConfig(name="opencode")}
    base.update(kwargs)
    return RepoHeartConfig(**base)  # type: ignore[arg-type]


def test_is_enabled_default_true() -> None:
    config = AgentsConfig()
    assert config.is_enabled("issue_triage") is True
    assert config.is_enabled("duplicate_detection") is True


def test_is_enabled_default_false() -> None:
    config = AgentsConfig()
    assert config.is_enabled("documentation") is False
    assert config.is_enabled("test") is False


def test_is_enabled_unknown_agent() -> None:
    config = AgentsConfig()
    assert config.is_enabled("nonexistent_agent") is False


def test_provider_for_agent_falls_back_to_global() -> None:
    config = _default_config()
    assert config.provider_for_agent("issue_triage") == "opencode"


def test_provider_for_agent_uses_override() -> None:
    providers = ProvidersConfig(agents={"issue_triage": "claude"})
    config = _default_config(providers=providers)
    assert config.provider_for_agent("issue_triage") == "claude"
    assert config.provider_for_agent("pr_review") == "opencode"


def test_limits_defaults() -> None:
    limits = LimitsConfig()
    assert limits.max_llm_calls == 30
    assert limits.max_files_read == 200
    assert limits.max_runtime_seconds == 600


def test_automation_defaults() -> None:
    auto = AutomationConfig()
    assert auto.level == "assist"
    assert "HIGH" in auto.require_human_approval
    assert "MEDIUM" in auto.require_human_approval


def test_config_is_frozen() -> None:
    import pytest

    config = _default_config()
    with pytest.raises((AttributeError, TypeError)):
        config.provider = ProviderConfig(name="claude")  # type: ignore[misc]
