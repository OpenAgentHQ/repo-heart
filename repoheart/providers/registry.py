"""Provider registry — factory + resolution from config.

``build_provider`` dispatches on provider name and returns a concrete instance.
``resolve_provider`` respects per-agent overrides from config and caches
instances by (name, model) so each unique combo is constructed once per process.
"""

from __future__ import annotations

from repoheart.config.loader import ConfigError
from repoheart.config.schema import RepoHeartConfig
from repoheart.providers.base import Provider, ProviderError

# Module-level cache: (provider_name, model) → Provider instance.
# Each GitHub Actions run is a fresh process, so this never crosses run
# boundaries (stateless by design).
_cache: dict[tuple[str, str], Provider] = {}


def build_provider(
    provider_name: str,
    model: str,
    *,
    timeout: float = 30.0,
) -> Provider:
    """Instantiate the named provider.

    Args:
        provider_name: One of the validated names from config.
        model: Forwarded from ``ProviderConfig.model``; may be empty.
        timeout: Per-request timeout in seconds.

    Raises:
        ProviderError: If the required SDK is not installed, or the provider
            is not yet implemented.
        ConfigError: If ``provider_name`` is not recognised.
    """
    match provider_name:
        case "opencode":
            from repoheart.providers.opencode import OpenCodeProvider

            return OpenCodeProvider(model, timeout=timeout)
        case "claude":
            from repoheart.providers.claude import ClaudeProvider

            return ClaudeProvider(model, timeout=timeout)
        case "openai":
            from repoheart.providers.openai import OpenAIProvider

            return OpenAIProvider(model, timeout=timeout)
        case "openrouter":
            from repoheart.providers.openrouter import OpenRouterProvider

            return OpenRouterProvider(model, timeout=timeout)
        case "gemini":
            raise ProviderError("gemini provider is not yet implemented")
        case "local":
            raise ProviderError("local provider is not yet implemented")
        case _:
            raise ConfigError(f"Unknown provider: {provider_name!r}")


def resolve_provider(
    config: RepoHeartConfig,
    agent_name: str,
    *,
    timeout: float = 30.0,
) -> Provider:
    """Return the appropriate Provider for *agent_name*, using a process cache.

    Respects ``repoheart.providers.agents.<agent_name>`` overrides from config.
    Agents that share the same (provider_name, model) pair receive the same
    cached instance.
    """
    name = config.provider_for_agent(agent_name)
    # Use global model only when the agent maps to the global provider.
    model = config.provider.model if name == config.provider.name else ""
    key = (name, model)
    if key not in _cache:
        _cache[key] = build_provider(name, model, timeout=timeout)
    return _cache[key]


def clear_cache() -> None:
    """Remove all cached provider instances. Useful in tests."""
    _cache.clear()
