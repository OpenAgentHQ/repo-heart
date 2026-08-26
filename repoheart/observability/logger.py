"""Structured single-line logger.

Emits ``key=value`` records to stdout so the GitHub Actions run log becomes a
machine-readable audit trail. Every proposed action and Safety Gate decision
must be logged here.

Also emits GitHub Actions workflow commands (``::group::``/``::error::``/
``::warning::``) so a single step's raw log stays readable in the Actions UI
without needing a separate job per internal stage. These are plain stdout
strings — harmless (just printed) when not running under Actions.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


class StructuredLogger:
    def log(self, **kwargs: Any) -> None:
        """Emit a single structured log line to stdout."""
        parts = " ".join(f"{k}={v}" for k, v in kwargs.items())
        print(parts, flush=True, file=sys.stdout)

    @contextmanager
    def group(self, title: str) -> Iterator[None]:
        """Bracket a block of log output as a collapsible group in the Actions UI."""
        print(f"::group::{title}", flush=True, file=sys.stdout)
        try:
            yield
        finally:
            print("::endgroup::", flush=True, file=sys.stdout)

    def error(self, message: str) -> None:
        """Emit a GitHub Actions error annotation."""
        print(f"::error::{message}", flush=True, file=sys.stdout)

    def warning(self, message: str) -> None:
        """Emit a GitHub Actions warning annotation."""
        print(f"::warning::{message}", flush=True, file=sys.stdout)
