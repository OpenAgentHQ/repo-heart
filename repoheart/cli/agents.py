"""Agent registry for the repoheart init CLI.

To add a new agent: add one entry to _AGENT_REGISTRY (name + description).
Order here determines the order in the generated repoheart.yml.
Nothing else needs to change.
"""

from __future__ import annotations

# Single source of truth: (agent_name, one-line description)
_AGENT_REGISTRY: list[tuple[str, str]] = [
    ("issue_triage",        "label and prioritize new issues"),
    ("duplicate_detection", "detect and link duplicate issues"),
    ("issue_resolution",    "suggest fixes for open issues"),
    ("pr_review",           "review pull request code changes"),
    ("code_quality",        "flag style, complexity, and maintainability issues"),
    ("security",            "scan for secrets and vulnerability patterns"),
    ("ci_repair",           "diagnose and suggest fixes for failing CI"),
    ("conflict_resolution", "detect and help resolve merge conflicts"),
    ("test",                "suggest missing tests for changed code"),
    ("documentation",       "keep docs and changelogs in sync with code"),
]

AGENTS: list[str] = [name for name, _ in _AGENT_REGISTRY]
AGENT_DESCRIPTIONS: dict[str, str] = dict(_AGENT_REGISTRY)


def select_agents(yes: bool) -> dict[str, bool]:
    """Return {agent_name: enabled}. Prompts interactively unless yes=True."""
    if yes:
        return {name: True for name in AGENTS}
    print("\nEnable agents (press Enter to accept default 'y'):")
    result: dict[str, bool] = {}
    for name in AGENTS:
        desc = AGENT_DESCRIPTIONS.get(name, "")
        label = f"  {name}  ({desc})" if desc else f"  {name}"
        raw = input(f"{label}? [Y/n]: ").strip().lower()
        result[name] = raw not in ("n", "no")
    return result
