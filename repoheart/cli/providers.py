"""Provider registry for the repoheart init CLI.

To add a new provider: add one entry to PROVIDERS and DEFAULT_MODELS.
Nothing else needs to change.
"""

from __future__ import annotations

import sys

# provider name → required secret env-var (None = no credential needed)
PROVIDERS: dict[str, str | None] = {
    "opencode": "OPENCODE_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "local": None,
}

# Suggested default model per provider shown during interactive init
DEFAULT_MODELS: dict[str, str] = {
    "opencode": "your-model",
    "claude": "claude-sonnet-4-6",
    "openai": "gpt-4o",
    "gemini": "gemini-2.0-flash",
    "openrouter": "openai/gpt-4o",
    "local": "your-model",
}


def select_provider(yes: bool) -> tuple[str, str | None]:
    """Return (provider_name, secret_env_var). Prompts interactively unless yes=True."""
    provider_list = list(PROVIDERS.keys())
    if yes:
        chosen = provider_list[0]
    else:
        print("\nAvailable providers:")
        for i, name in enumerate(provider_list, 1):
            default_model = DEFAULT_MODELS.get(name, "your-model")
            print(f"  {i}. {name:<12} → default model: {default_model}")
        raw = input(f"Choose provider [1-{len(provider_list)}] (default 1): ").strip()
        try:
            idx = int(raw) - 1 if raw else 0
            chosen = provider_list[idx]
        except (ValueError, IndexError):
            print(f"Invalid choice, using '{provider_list[0]}'", file=sys.stderr)
            chosen = provider_list[0]
    return chosen, PROVIDERS[chosen]
