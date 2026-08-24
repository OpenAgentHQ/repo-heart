"""Load and validate opencode.yml, returning a typed RepoHeartConfig.

This is the fail-fast boundary: any misconfiguration raises ``ConfigError``
before any agent or API call is made. The caller should treat a ``ConfigError``
as a hard stop and exit with a non-zero code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from repoheart.config.schema import (
    AgentsConfig,
    AutomationConfig,
    CIConfig,
    LabelsConfig,
    LimitsConfig,
    ProviderConfig,
    ProvidersConfig,
    RepoHeartConfig,
    ScaleConfig,
)

_VALID_PROVIDERS = {"opencode", "claude", "openai", "gemini", "local"}
_VALID_AUTOMATION_LEVELS = {"assist", "auto-safe", "auto"}
_VALID_RISK_NAMES = {"SAFE", "LOW", "MEDIUM", "HIGH"}


class ConfigError(ValueError):
    """Raised when opencode.yml is missing, unparseable, or semantically invalid."""


def load_config(path: str | Path) -> RepoHeartConfig:
    """Load, parse, and validate opencode.yml.

    Raises:
        ConfigError: if the file is missing, unreadable, not valid YAML, or
            fails semantic validation.
    """
    resolved = Path(path)
    if not resolved.is_file():
        raise ConfigError(f"Config file not found: {resolved}")

    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse YAML in {resolved}: {exc}") from exc

    if not isinstance(raw, dict) or "repoheart" not in raw:
        raise ConfigError(
            f"Config {resolved} must have a top-level 'repoheart' key"
        )

    cfg = raw["repoheart"]
    if not isinstance(cfg, dict):
        raise ConfigError(f"'repoheart' in {resolved} must be a mapping")

    return _build_config(cfg, resolved)


def _build_config(cfg: dict[str, Any], path: Path) -> RepoHeartConfig:
    provider = _load_provider(cfg, path)
    providers = _load_providers(cfg)
    agents = _load_agents(cfg)
    automation = _load_automation(cfg, path)
    scale = _load_scale(cfg)
    labels = _load_labels(cfg)
    ci = _load_ci(cfg)

    return RepoHeartConfig(
        provider=provider,
        providers=providers,
        agents=agents,
        automation=automation,
        scale=scale,
        labels=labels,
        ci=ci,
    )


def _load_provider(cfg: dict[str, Any], path: Path) -> ProviderConfig:
    raw = cfg.get("provider", {})
    if not isinstance(raw, dict):
        raise ConfigError(f"'provider' in {path} must be a mapping")
    name = raw.get("name", "")
    if not isinstance(name, str) or name not in _VALID_PROVIDERS:
        raise ConfigError(
            f"Unknown provider {name!r} in {path}. "
            f"Valid values: {sorted(_VALID_PROVIDERS)}"
        )
    model = str(raw.get("model", ""))
    return ProviderConfig(name=name, model=model)


def _load_providers(cfg: dict[str, Any]) -> ProvidersConfig:
    raw = cfg.get("providers", {}) or {}
    if not isinstance(raw, dict):
        return ProvidersConfig()
    agents_map = raw.get("agents", {}) or {}
    if not isinstance(agents_map, dict):
        return ProvidersConfig()
    return ProvidersConfig(agents={str(k): str(v) for k, v in agents_map.items()})


def _load_agents(cfg: dict[str, Any]) -> AgentsConfig:
    raw = cfg.get("agents", {}) or {}
    if not isinstance(raw, dict):
        return AgentsConfig()
    fields = {
        "issue_triage", "duplicate_detection", "issue_resolution", "pr_review",
        "code_quality", "security", "ci_repair", "conflict_resolution", "test",
        "documentation",
    }
    kwargs: dict[str, bool] = {}
    for field in fields:
        if field in raw:
            kwargs[field] = bool(raw[field])
    return AgentsConfig(**kwargs)


def _load_automation(cfg: dict[str, Any], path: Path) -> AutomationConfig:
    raw = cfg.get("automation", {}) or {}
    if not isinstance(raw, dict):
        return AutomationConfig()

    level = raw.get("level", "assist")
    if not isinstance(level, str) or level not in _VALID_AUTOMATION_LEVELS:
        raise ConfigError(
            f"Invalid automation.level {level!r} in {path}. "
            f"Valid values: {sorted(_VALID_AUTOMATION_LEVELS)}"
        )

    require = raw.get("require_human_approval", ["HIGH", "MEDIUM"])
    if not isinstance(require, list):
        raise ConfigError(
            f"automation.require_human_approval in {path} must be a list"
        )
    for item in require:
        if item not in _VALID_RISK_NAMES:
            raise ConfigError(
                f"Invalid risk level {item!r} in automation.require_human_approval "
                f"in {path}. Valid values: {sorted(_VALID_RISK_NAMES)}"
            )

    return AutomationConfig(level=level, require_human_approval=list(require))


def _load_scale(cfg: dict[str, Any]) -> ScaleConfig:
    raw = cfg.get("scale", {}) or {}
    if not isinstance(raw, dict):
        return ScaleConfig()

    checkout = str(raw.get("checkout", "event-scoped"))

    retrieval = raw.get("retrieval", {}) or {}
    semantic = (
        bool(retrieval.get("semantic", False)) if isinstance(retrieval, dict) else False
    )

    cache = raw.get("cache", {}) or {}
    cache_backend = (
        str(cache.get("backend", "actions")) if isinstance(cache, dict) else "actions"
    )

    limits_raw = raw.get("limits", {}) or {}
    limits = LimitsConfig(
        max_llm_calls=int((limits_raw or {}).get("max_llm_calls", 30)),
        max_files_read=int((limits_raw or {}).get("max_files_read", 200)),
        max_runtime_seconds=int((limits_raw or {}).get("max_runtime_seconds", 600)),
    ) if isinstance(limits_raw, dict) else LimitsConfig()

    return ScaleConfig(
        checkout=checkout,
        semantic=semantic,
        cache_backend=cache_backend,
        limits=limits,
    )


def _load_labels(cfg: dict[str, Any]) -> LabelsConfig:
    raw = cfg.get("labels", {}) or {}
    if not isinstance(raw, dict):
        return LabelsConfig()
    return LabelsConfig(
        triaged=str(raw.get("triaged", "repoheart:triaged")),
        reviewed=str(raw.get("reviewed", "repoheart:reviewed")),
        needs_human=str(raw.get("needs_human", "repoheart:needs-human")),
    )


def _load_ci(cfg: dict[str, Any]) -> CIConfig:
    raw = cfg.get("ci", {}) or {}
    if not isinstance(raw, dict):
        return CIConfig()
    watch = raw.get("watch_workflows", []) or []
    max_attempts = int(raw.get("max_fix_attempts", 2))
    return CIConfig(
        watch_workflows=[str(w) for w in watch] if isinstance(watch, list) else [],
        max_fix_attempts=max_attempts,
    )
