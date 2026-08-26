"""repoheart init — zero-copy onboarding command.

Orchestrates provider selection, agent selection, and file generation.
Data and rendering live in sibling modules; this file is pure control flow.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from repoheart.cli.agents import AGENT_DESCRIPTIONS, select_agents
from repoheart.cli.providers import DEFAULT_MODELS, PROVIDERS, select_provider
from repoheart.cli.templates import (
    prompt_or_default,
    render_config,
    render_workflow,
    write_file,
)


def run_init(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).resolve()
    yes: bool = args.yes
    force: bool = args.force

    print("RepoHeart init — zero-copy onboarding\n")

    # Provider
    if args.provider:
        provider = args.provider
        secret = PROVIDERS.get(provider)
    else:
        provider, secret = select_provider(yes)

    # Model
    if args.model:
        model = args.model
    else:
        model = prompt_or_default(
            f"Model for {provider}",
            DEFAULT_MODELS.get(provider, "your-model"),
            yes,
        )

    # Automation level
    automation_level = prompt_or_default(
        "Automation level (assist / auto-safe / auto)", "assist", yes
    )
    if automation_level not in ("assist", "auto-safe", "auto"):
        print(
            f"Unknown automation level '{automation_level}', defaulting to 'assist'",
            file=sys.stderr,
        )
        automation_level = "assist"

    # Agents
    agents = select_agents(yes)

    # Render
    config_content = render_config(provider, model, agents, automation_level, AGENT_DESCRIPTIONS)
    workflow_content = render_workflow()

    config_path = output_dir / "repoheart.yml"
    workflow_path = output_dir / ".github" / "workflows" / "repoheart.yml"

    # Write
    try:
        write_file(config_path, config_content, force)
        write_file(workflow_path, workflow_content, force)
    except FileExistsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Summary
    print(f"\n  [ok] {config_path.relative_to(output_dir)}")
    print(f"  [ok] {workflow_path.relative_to(output_dir)}")

    print("\nNext steps:")
    if secret:
        print(
            f"  1. Add your {secret} secret in GitHub"
            " -> Settings -> Secrets and variables -> Actions -> New repository secret"
        )
        print("  2. Commit both files and push")
        print("  3. Open an issue to verify RepoHeart responds")
    else:
        print("  1. Commit both files and push")
        print("  2. Open an issue to verify RepoHeart responds")

    print(
        "\nDocs: https://github.com/OpenAgentHQ/repo-heart/blob/main/docs/quickstart.md"
    )
    return 0
