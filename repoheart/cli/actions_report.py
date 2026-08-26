"""GitHub Actions observability artifacts: agent plan + per-agent results.

These build the small, secret-free JSON files ``main.py`` writes into
``.repoheart/`` inside the workspace so a GitHub Actions workflow can render
per-agent activation, skip, and failure state in the job graph and step
summary. No agent business logic lives here — this only reports on the
routing table and orchestrator outcomes that already exist elsewhere.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from repoheart.agents.registry import AGENT_REGISTRY
from repoheart.config.schema import RepoHeartConfig
from repoheart.events.router import route
from repoheart.events.types import InternalEvent

RESULT_DIR = ".repoheart"


_ACRONYMS = {"pr": "PR", "ci": "CI"}

# Purely cosmetic — used only for Actions UI job names / step summary rows.
_EMOJI = {
    "issue_triage": "🐛",
    "duplicate_detection": "🔍",
    "issue_resolution": "🩹",
    "pr_review": "🔬",
    "code_quality": "🧹",
    "security": "🛡️",
    "ci_repair": "🔧",
    "conflict_resolution": "🤝",
    "test": "🧪",
    "documentation": "📚",
}


def agent_label(agent_name: str) -> str:
    """Title-case an agent registry key into a human-readable job label."""
    words = agent_name.split("_")
    return " ".join(_ACRONYMS.get(w, w.title()) for w in words)


def agent_emoji(agent_name: str) -> str:
    return _EMOJI.get(agent_name, "🤖")


def _provider_and_model(config: RepoHeartConfig, agent_name: str) -> tuple[str, str]:
    """Mirror providers/registry.py's resolution so reported values match reality."""
    provider_name = config.provider_for_agent(agent_name)
    model = config.provider.model if provider_name == config.provider.name else ""
    return provider_name, model


def build_plan(event: InternalEvent, config: RepoHeartConfig) -> dict[str, Any]:
    """Compute the full per-agent activation plan for this event.

    Includes every agent in ``AGENT_REGISTRY`` — not just activated ones — so
    the workflow's matrix can render inactive agents as native GitHub Actions
    "Skipped" jobs instead of omitting them from the graph.
    """
    activated = set(route(event, config))
    agents = []
    for name, cls in AGENT_REGISTRY.items():
        provider_name, model = _provider_and_model(config, name)
        agents.append(
            {
                "id": name,
                "label": agent_label(name),
                "emoji": agent_emoji(name),
                "activated": name in activated,
                "blocking": cls.blocking,
                "provider": provider_name,
                "model": model,
            }
        )
    return {
        "event": event.routing_key,
        "repo": event.repo_full_name,
        "agents": agents,
        "agent_ids": sorted(activated),
    }


def write_plan(plan: dict[str, Any], workspace: str) -> Path:
    out_path = Path(workspace) / RESULT_DIR / "plan.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return out_path


def build_result(
    *,
    agent_name: str,
    activated: bool,
    status: str,
    stage: str,
    error: str,
    findings: int,
    actions: int,
    provider: str,
    model: str,
    blocking: bool,
) -> dict[str, Any]:
    """Assemble the per-agent result record.

    ``status`` is one of ``"ok"``, ``"error"``, or ``"skipped"``. ``stage`` is
    the coarse pipeline stage reached (``config_load``, ``event_parse``,
    ``provider_init``, ``agent_execution``, ``complete``) — the orchestrator
    doesn't expose finer boundaries (e.g. retrieval vs. AI-analysis) today, so
    this deliberately doesn't fabricate stages it can't actually observe.
    """
    return {
        "agent": agent_name,
        "label": agent_label(agent_name),
        "emoji": agent_emoji(agent_name),
        "activated": activated,
        "status": status,
        "stage": stage,
        "error": error,
        "findings": findings,
        "actions": actions,
        "provider": provider,
        "model": model,
        "blocking": blocking,
    }


def write_result(result: dict[str, Any], workspace: str) -> Path:
    out_path = Path(workspace) / RESULT_DIR / f"result-{result['agent']}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return out_path
