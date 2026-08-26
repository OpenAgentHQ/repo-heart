"""RepoHeart entrypoint — full pipeline + init CLI.

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
from repoheart.cli.actions_report import build_plan, build_result, write_plan, write_result
from repoheart.cli.init import run_init
from repoheart.cli.providers import PROVIDERS
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
    parser.add_argument("--version", action="store_true", help="Print version and exit.")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.default = "run"

    # --- run subcommand (existing pipeline) ---
    run_p = subparsers.add_parser("run", help="Process a GitHub event (default).")
    run_p.add_argument(
        "--event",
        help="Path to a GitHub event payload JSON. "
        "Defaults to $GITHUB_EVENT_PATH when unset.",
    )
    run_p.add_argument(
        "--config",
        default="repoheart.yml",
        help="Path to the repoheart.yml config file.",
    )
    run_p.add_argument(
        "--agent",
        default="",
        help="Run only this single agent (by registry name) instead of the "
        "full routed list. Empty/unset runs every agent the router selects, "
        "same as before. An agent not selected for this event is reported "
        "as skipped rather than run.",
    )

    # --- plan subcommand ---
    plan_p = subparsers.add_parser(
        "plan",
        help="Compute per-agent activation for an event without running anything.",
    )
    plan_p.add_argument(
        "--event",
        help="Path to a GitHub event payload JSON. "
        "Defaults to $GITHUB_EVENT_PATH when unset.",
    )
    plan_p.add_argument(
        "--config",
        default="repoheart.yml",
        help="Path to the repoheart.yml config file.",
    )
    plan_p.add_argument(
        "--agent",
        default="",
        help=argparse.SUPPRESS,  # accepted so action.yml can pass --agent unconditionally; unused
    )

    # --- init subcommand ---
    init_p = subparsers.add_parser(
        "init",
        help="Generate repoheart.yml and .github/workflows/repoheart.yml.",
    )
    init_p.add_argument(
        "--provider",
        choices=list(PROVIDERS.keys()),
        help="AI provider (skips interactive prompt).",
    )
    init_p.add_argument(
        "--model",
        help="Model identifier for the chosen provider.",
    )
    init_p.add_argument(
        "--output-dir",
        default=".",
        help="Directory to write files into (default: current directory).",
    )
    init_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files without prompting.",
    )
    init_p.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Non-interactive mode: accept all defaults.",
    )

    # Support legacy flat invocation: `repoheart --event X --config Y`
    # by also accepting these flags at the top level when no subcommand given.
    parser.add_argument(
        "--event",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--config",
        default="repoheart.yml",
        help=argparse.SUPPRESS,
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    log = StructuredLogger()

    if args.version:
        print(__version__)
        return 0

    if args.command == "init":
        return run_init(args)

    if args.command == "plan":
        return _run_plan(args, log)

    # --- run pipeline ---
    agent_filter = getattr(args, "agent", "") or None
    repo_root = os.environ.get("GITHUB_WORKSPACE", ".")
    stage = "config_load"

    def _fail_agent(status: str, error: str, provider: str = "", model: str = "") -> None:
        """When running a single agent for CI matrix visibility, record why."""
        if agent_filter is None:
            return
        result = build_result(
            agent_name=agent_filter,
            activated=status != "skipped",
            status=status,
            stage=stage,
            error=error,
            findings=0,
            actions=0,
            provider=provider,
            model=model,
            blocking=getattr(AGENT_REGISTRY.get(agent_filter), "blocking", True),
        )
        write_result(result, repo_root)
        if status == "error":
            log.error(f"agent={agent_filter} stage={stage} reason={error}")

    # 1. Resolve event path
    event_path = getattr(args, "event", None) or os.environ.get("GITHUB_EVENT_PATH")
    log.log(
        event_msg="startup",
        version=__version__,
        config=args.config,
        event_path=event_path or "none",
        agent=agent_filter or "all",
    )

    if not event_path:
        log.log(
            event_msg="error",
            reason="no_event_path",
            detail="Set --event or GITHUB_EVENT_PATH",
        )
        _fail_agent("error", "no_event_path")
        return 1

    # 2. Load config — fail fast
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        log.log(event_msg="error", reason="config_invalid", detail=str(exc))
        _fail_agent("error", f"config_invalid: {exc}")
        return 1

    log.log(
        event_msg="config_loaded",
        provider=config.provider.name,
        automation_level=config.automation.level,
    )

    if agent_filter is not None and agent_filter not in AGENT_REGISTRY:
        detail = f"'{agent_filter}' is not a registered agent"
        log.log(event_msg="error", reason="unknown_agent", detail=detail)
        _fail_agent("error", detail)
        return 1

    # 2b. Build provider factory — fail fast if SDK is missing
    stage = "provider_init"

    def _provider_factory(agent_name: str) -> Provider:
        return resolve_provider(config, agent_name)

    probe_agent = agent_filter or next(iter(AGENT_REGISTRY), None)
    probe_provider = config.provider_for_agent(probe_agent) if probe_agent else ""
    if probe_agent is not None:
        try:
            _provider_factory(probe_agent)
        except ProviderError as exc:
            log.log(event_msg="error", reason="provider_init_failed", detail=str(exc))
            _fail_agent("error", str(exc), provider=probe_provider)
            return 1

    # 3. Load and normalize event
    stage = "event_parse"
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    try:
        if not event_name:
            import json
            raw = json.loads(Path(event_path).read_text(encoding="utf-8"))
            event_name = infer_event_name(raw)
        event = load_event(event_path, event_name)
    except (EventLoadError, FileNotFoundError, OSError) as exc:
        log.log(event_msg="error", reason="event_invalid", detail=str(exc))
        _fail_agent("error", str(exc), provider=probe_provider)
        return 1
    except Exception as exc:  # json.JSONDecodeError, etc.
        log.log(event_msg="error", reason="event_invalid", detail=str(exc))
        _fail_agent("error", str(exc), provider=probe_provider)
        return 1

    log.log(
        event_msg="event_parsed",
        routing_key=event.routing_key,
        repo=event.repo_full_name,
        sender=event.sender_login,
    )

    # 4. Route event → candidate agents
    routed_names = route(event, config)
    if agent_filter is not None:
        if agent_filter not in routed_names:
            # Not selected for this event — report as skipped, not failed.
            log.log(
                event_msg="agent_not_activated",
                agent=agent_filter,
                routing_key=event.routing_key,
            )
            _fail_agent("skipped", "")
            return 0
        agent_names = [agent_filter]
    else:
        agent_names = routed_names

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
    stage = "agent_execution"
    with log.group(f"RepoHeart: {', '.join(agent_names)}"):
        summary = orchestrator.run(event, agent_names)
    stage = "complete"

    log.log(
        event_msg="run_complete",
        agents_run=",".join(summary.agents_run) or "none",
        actions_taken=summary.actions_taken,
        actions_escalated=summary.actions_escalated,
        actions_denied=summary.actions_denied,
        errors=len(summary.errors),
    )

    if agent_filter is not None:
        ran_ok = agent_filter in summary.agents_run
        agent_errors = [e for e in summary.errors if f"'{agent_filter}'" in e]
        status = "ok" if ran_ok else "error"
        error_text = "; ".join(agent_errors) if agent_errors else (
            "" if ran_ok else "agent did not complete (see run log)"
        )
        provider_name, model = probe_provider, (
            config.provider.model if probe_provider == config.provider.name else ""
        )
        result = build_result(
            agent_name=agent_filter,
            activated=True,
            status=status,
            stage=stage,
            error=error_text,
            findings=len(summary.errors) if not ran_ok else 0,
            actions=summary.actions_taken,
            provider=provider_name,
            model=model,
            blocking=AGENT_REGISTRY[agent_filter].blocking,
        )
        write_result(result, repo_root)
        if status == "error":
            log.error(f"agent={agent_filter} stage={stage} reason={error_text}")
            return 1
        return 0

    return 1 if summary.errors else 0


def _run_plan(args: argparse.Namespace, log: StructuredLogger) -> int:
    """Compute per-agent activation for an event and write .repoheart/plan.json.

    Pure and side-effect-free besides that one file: no GitHub calls, no LLM
    calls. Used by the GitHub Actions "plan" job to size the agent matrix.
    """
    event_path = getattr(args, "event", None) or os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        log.log(
            event_msg="error",
            reason="no_event_path",
            detail="Set --event or GITHUB_EVENT_PATH",
        )
        return 1

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        log.log(event_msg="error", reason="config_invalid", detail=str(exc))
        return 1

    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    try:
        if not event_name:
            import json
            raw = json.loads(Path(event_path).read_text(encoding="utf-8"))
            event_name = infer_event_name(raw)
        event = load_event(event_path, event_name)
    except Exception as exc:
        log.log(event_msg="error", reason="event_invalid", detail=str(exc))
        return 1

    plan = build_plan(event, config)
    repo_root = os.environ.get("GITHUB_WORKSPACE", ".")
    out_path = write_plan(plan, repo_root)

    import json as _json

    print(_json.dumps(plan))
    log.log(
        event_msg="plan_written",
        path=str(out_path),
        routing_key=plan["event"],
        activated=",".join(plan["agent_ids"]) or "none",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
