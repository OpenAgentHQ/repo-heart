"""Tests for providers/registry.py — factory + resolution + cache."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from repoheart.config.loader import ConfigError
from repoheart.config.schema import ProviderConfig, ProvidersConfig, RepoHeartConfig
from repoheart.providers.base import ProviderError
from repoheart.providers.mock import CannedResponse, MockProvider
from repoheart.providers.opencode import OpenCodeProvider
from repoheart.providers.registry import build_provider, clear_cache, resolve_provider


def _make_config(
    provider_name: str = "opencode",
    model: str = "",
    agent_overrides: dict[str, str] | None = None,
) -> RepoHeartConfig:
    from repoheart.config.schema import (
        AgentsConfig,
        AutomationConfig,
        CIConfig,
        LabelsConfig,
        ScaleConfig,
    )

    return RepoHeartConfig(
        provider=ProviderConfig(name=provider_name, model=model),
        providers=ProvidersConfig(agents=agent_overrides or {}),
        automation=AutomationConfig(),
        agents=AgentsConfig(),
        scale=ScaleConfig(),
        labels=LabelsConfig(),
        ci=CIConfig(),
    )


@pytest.fixture(autouse=True)
def _clear_provider_cache() -> None:
    clear_cache()


# ---------------------------------------------------------------------------
# build_provider
# ---------------------------------------------------------------------------


def test_build_opencode_returns_instance() -> None:
    p = build_provider("opencode", "")
    assert isinstance(p, OpenCodeProvider)


def test_build_unknown_raises_config_error() -> None:
    with pytest.raises(ConfigError):
        build_provider("unknown", "")


def test_build_gemini_raises_provider_error() -> None:
    with pytest.raises(ProviderError, match="not yet implemented"):
        build_provider("gemini", "")


def test_build_local_raises_provider_error() -> None:
    with pytest.raises(ProviderError, match="not yet implemented"):
        build_provider("local", "")


def test_build_claude_missing_sdk_raises_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_modules = {k: v for k, v in sys.modules.items() if k != "anthropic"}
    original_import = __import__

    def _fake_import(name: str, *args: object, **kwargs: object) -> ModuleType:
        if name == "anthropic":
            raise ImportError("No module named 'anthropic'")
        return original_import(name, *args, **kwargs)  # type: ignore[call-arg]

    with (
        patch.dict(sys.modules, fake_modules, clear=False),
        patch("builtins.__import__", side_effect=_fake_import),
        pytest.raises(ProviderError, match="repoheart\\[claude\\]"),
    ):
        build_provider("claude", "")


def test_build_openai_missing_sdk_raises_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = __import__

    def _fake_import(name: str, *args: object, **kwargs: object) -> ModuleType:
        if name == "openai":
            raise ImportError("No module named 'openai'")
        return original_import(name, *args, **kwargs)  # type: ignore[call-arg]

    with (
        patch("builtins.__import__", side_effect=_fake_import),
        pytest.raises(ProviderError, match="repoheart\\[openai\\]"),
    ):
        build_provider("openai", "")


# ---------------------------------------------------------------------------
# resolve_provider
# ---------------------------------------------------------------------------


def test_resolve_uses_global_provider() -> None:
    config = _make_config("opencode")
    p = resolve_provider(config, "issue_triage")
    assert isinstance(p, OpenCodeProvider)


def test_resolve_cache_returns_same_instance() -> None:
    config = _make_config("opencode")
    p1 = resolve_provider(config, "issue_triage")
    p2 = resolve_provider(config, "pr_review")
    assert p1 is p2  # same (opencode, "") key → same object


def test_resolve_per_agent_override() -> None:
    config = _make_config("opencode", agent_overrides={"issue_triage": "opencode"})
    p = resolve_provider(config, "issue_triage")
    assert isinstance(p, OpenCodeProvider)


def test_clear_cache_resets_instances() -> None:
    config = _make_config("opencode")
    p1 = resolve_provider(config, "issue_triage")
    clear_cache()
    p2 = resolve_provider(config, "issue_triage")
    assert p1 is not p2  # new instance after cache cleared


# ---------------------------------------------------------------------------
# Integration: orchestrator with MockProvider factory
# ---------------------------------------------------------------------------


def test_orchestrator_with_mock_provider_factory() -> None:
    """Pipeline runs end-to-end with a MockProvider injected via provider_factory."""

    from repoheart.events.types import InternalEvent
    from repoheart.observability.logger import StructuredLogger
    from repoheart.orchestrator.orchestrator import Orchestrator
    from repoheart.safety.gate import SafetyGate

    config = _make_config("opencode")
    mock_provider = MockProvider(default_response=CannedResponse("ok"))

    log = StructuredLogger()
    github_client = MagicMock()
    github_client._token = ""
    git_repo = MagicMock()
    safety_gate = SafetyGate(config=config, logger=log)
    markers = MagicMock()

    orchestrator = Orchestrator(
        config=config,
        github_client=github_client,
        git_repo=git_repo,
        safety_gate=safety_gate,
        markers=markers,
        logger=log,
        provider_factory=lambda _agent_name: mock_provider,
    )

    event = InternalEvent(
        event_name="issues",
        action="opened",
        repo_full_name="owner/repo",
        payload={"issue": {"number": 1, "title": "t", "body": "b"}},
        sender_login="user",
    )

    summary = orchestrator.run(event, ["issue_triage"])
    assert "issue_triage" in summary.agents_run
    assert not summary.errors
