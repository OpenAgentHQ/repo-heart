"""Structured single-line logger.

Emits ``key=value`` records to stdout so the GitHub Actions run log becomes a
machine-readable audit trail. Every proposed action and Safety Gate decision
must be logged here.
"""

from __future__ import annotations

import sys
from typing import Any


class StructuredLogger:
    def log(self, **kwargs: Any) -> None:
        """Emit a single structured log line to stdout."""
        parts = " ".join(f"{k}={v}" for k, v in kwargs.items())
        print(parts, flush=True, file=sys.stdout)
