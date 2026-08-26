"""RepoHeart entrypoint — Phase 1 full pipeline.

Wires config loading → event parsing → routing → orchestration → safety gate
into a single, stateless run. No LLM calls are made in Phase 1; the orchestrator
runs NoOpAgent placeholders for every agent slot.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from repoheart import __version__
from repoheart.agents.registry import AGENT_REGISTRY
from repoheart.cache import make_cache
from repoheart.config.loader import ConfigError, load_config
from repoheart.events.context import EventLoadError, infer_event_name, load_event
from repoheart.events.router import route
from repoheart.git_ops.repo import GitRepo
from repoheart.github_ops.budgeter import RateLimiter
from repoheart.github_ops.client import GitHubClient
from repoheart.idempotency.markers import IdempotencyMarkers
from repoheart.observability.logger import StructuredLogger
from repoheart.orchestrator.orchestrator import Orchestrator
from repoheart.providers.base import Provider, ProviderError
from repoheart.providers.registry import resolve_provider
from repoheart.repo_access.reader import RepoReader
from repoheart.retrieval.chunking import FileChunker
from repoheart.retrieval.layer import RetrievalLayer
from repoheart.retrieval.lexical import LexicalRetriever
from repoheart.retrieval.semantic import SemanticRetriever
from repoheart.retrieval.structural import StructuralRetriever
from repoheart.safety.gate import SafetyGate


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="repoheart")
    parser.add_argument(
        "--event",
        help="Path to a GitHub event payload JSON. "
        "Defaults to $GITHUB_EVENT_PATH when unset.",
    )
    parser.add_argument(
        "--config",
        default="opencode.yml",
        help="Path to the opencode.yml config file.",
    )
    parser.add_argument("--version", action="store_true", help="Print version and exit.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    log = StructuredLogger()

    if args.version:
        print(__version__)
        return 0

    # 1. Resolve event path
    event_path = args.event or os.environ.get("GITHUB_EVENT_PATH")
    log.log(
        event_msg="startup",
        version=__version__,
        config=args.config,
        event_path=event_path or "none",
    )

    if not event_path:
        log.log(
            event_msg="error",
            reason="no_event_path",
            detail="Set --event or GITHUB_EVENT_PATH",
        )
        return 1

    # 2. Load config — fail fast
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        log.log(event_msg="error", reason="config_invalid", detail=str(exc))
        return 1

    log.log(
        event_msg="config_loaded",
        provider=config.provider.name,
        automation_level=config.automation.level,
    )

    # 2b. Build provider factory — fail fast if SDK is missing
    def _provider_factory(agent_name: str) -> Provider:
        return resolve_provider(config, agent_name)

    probe_agent = next(iter(AGENT_REGISTRY), None)
    if probe_agent is not None:
        try:
            _provider_factory(probe_agent)
        except ProviderError as exc:
            log.log(event_msg="error", reason="provider_init_failed", detail=str(exc))
            return 1

    # 3. Load and normalize event
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    try:
        if not event_name:
            import json
            raw = json.loads(Path(event_path).read_text(encoding="utf-8"))
            event_name = infer_event_name(raw)
        event = load_event(event_path, event_name)
    except (EventLoadError, FileNotFoundError, OSError) as exc:
        log.log(event_msg="error", reason="event_invalid", detail=str(exc))
        return 1
    except Exception as exc:  # json.JSONDecodeError, etc.
        log.log(event_msg="error", reason="event_invalid", detail=str(exc))
        return 1

    log.log(
        event_msg="event_parsed",
        routing_key=event.routing_key,
        repo=event.repo_full_name,
        sender=event.sender_login,
    )

    # 4. Route event → candidate agents
    agent_names = route(event, config)
    if not agent_names:
        log.log(
            event_msg="no_agents",
            routing_key=event.routing_key,
            reason="unknown_event_or_all_agents_disabled",
        )
        return 0

    log.log(event_msg="routed", agents=",".join(agent_names))

    # 5. Wire components
    token = os.environ.get("GITHUB_TOKEN", "")
    rate_limiter = RateLimiter()
    github_client = GitHubClient(token=token, rate_limiter=rate_limiter, logger=log)
    git_repo = GitRepo()
    safety_gate = SafetyGate(config=config, logger=log)
    markers = IdempotencyMarkers(client=github_client, logger=log)

    # Phase 5: cache + retrieval layer
    repo_root = os.environ.get("GITHUB_WORKSPACE", ".")
    cache = make_cache(config.scale.cache_backend, git_repo)
    reader = RepoReader(repo_root)
    retrieval_layer = RetrievalLayer(
        reader=reader,
        structural=StructuralRetriever(cache),
        lexical=LexicalRetriever(repo_root, github_client),
        chunker=FileChunker(),
        semantic=SemanticRetriever(cache) if config.scale.semantic else None,
    )

    orchestrator = Orchestrator(
        config=config,
        github_client=github_client,
        git_repo=git_repo,
        safety_gate=safety_gate,
        markers=markers,
        logger=log,
        provider_factory=_provider_factory,
        retrieval_layer=retrieval_layer,
    )

    # 6. Run
    summary = orchestrator.run(event, agent_names)

    log.log(
        event_msg="run_complete",
        agents_run=",".join(summary.agents_run) or "none",
        actions_taken=summary.actions_taken,
        actions_escalated=summary.actions_escalated,
        actions_denied=summary.actions_denied,
        errors=len(summary.errors),
    )

    return 1 if summary.errors else 0


if __name__ == "__main__":
    sys.exit(main())
