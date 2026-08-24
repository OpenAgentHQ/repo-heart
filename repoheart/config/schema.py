"""Typed dataclasses mirroring opencode.schema.json.

These are pure value objects — no file I/O, no imports from safety/ to avoid
circular dependencies. ``require_human_approval`` stores risk level names as
plain strings (e.g. ``"MEDIUM"``); conversion to ``RiskLevel`` enums happens
in ``safety/gate.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    model: str = ""


@dataclass(frozen=True)
class ProvidersConfig:
    agents: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentsConfig:
    issue_triage: bool = True
    duplicate_detection: bool = True
    issue_resolution: bool = True
    pr_review: bool = True
    code_quality: bool = True
    security: bool = True
    ci_repair: bool = True
    conflict_resolution: bool = True
    test: bool = False
    documentation: bool = False

    def is_enabled(self, agent_name: str) -> bool:
        """Return True if the named agent is enabled in config."""
        return bool(getattr(self, agent_name, False))


@dataclass(frozen=True)
class AutomationConfig:
    level: str = "assist"
    require_human_approval: list[str] = field(default_factory=lambda: ["HIGH", "MEDIUM"])


@dataclass(frozen=True)
class LimitsConfig:
    max_llm_calls: int = 30
    max_files_read: int = 200
    max_runtime_seconds: int = 600


@dataclass(frozen=True)
class ScaleConfig:
    checkout: str = "event-scoped"
    semantic: bool = False
    cache_backend: str = "actions"
    limits: LimitsConfig = field(default_factory=LimitsConfig)


@dataclass(frozen=True)
class LabelsConfig:
    triaged: str = "repoheart:triaged"
    reviewed: str = "repoheart:reviewed"
    needs_human: str = "repoheart:needs-human"


@dataclass(frozen=True)
class CIConfig:
    watch_workflows: list[str] = field(default_factory=list)
    max_fix_attempts: int = 2


@dataclass(frozen=True)
class RepoHeartConfig:
    provider: ProviderConfig
    providers: ProvidersConfig = field(default_factory=ProvidersConfig)
    automation: AutomationConfig = field(default_factory=AutomationConfig)
    agents: AgentsConfig = field(default_factory=AgentsConfig)
    scale: ScaleConfig = field(default_factory=ScaleConfig)
    labels: LabelsConfig = field(default_factory=LabelsConfig)
    ci: CIConfig = field(default_factory=CIConfig)

    def provider_for_agent(self, agent_name: str) -> str:
        """Return per-agent provider override, or fall back to global provider."""
        return self.providers.agents.get(agent_name, self.provider.name)
