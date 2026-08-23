"""RepoHeart entrypoint.

This is the single place the whole pipeline is wired together. In Phase 0 it is
a skeleton: it parses arguments, loads an event payload, and logs a startup
line. Subsequent phases fill in config loading, routing, orchestration, and
agent execution as described in docs/repoheart-final-system-design.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from repoheart import __version__
from repoheart.observability.logger import StructuredLogger


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

    event_path = args.event or os.environ.get("GITHUB_EVENT_PATH")
    log.log(
        event_msg="startup",
        version=__version__,
        config=args.config,
        event_path=event_path or "none",
    )

    if event_path and Path(event_path).is_file():
        try:
            payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            log.log(event_msg="error", reason="invalid event payload", detail=str(exc))
            return 1
        log.log(event_msg="event loaded", keys=",".join(sorted(payload.keys())) or "none")

    # Phase 1+ pipeline (config -> context -> idempotency -> route ->
    # orchestrate -> gate -> execute) is not yet implemented.
    log.log(event_msg="noop", detail="core pipeline not yet implemented (Phase 0 skeleton)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
