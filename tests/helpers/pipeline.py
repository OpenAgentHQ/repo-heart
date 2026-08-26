"""Helpers for exercising the complete local pipeline without external services."""

from __future__ import annotations

import os
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from repoheart.main import main

_CLEAN_ENV = {"GITHUB_TOKEN": "", "GITHUB_EVENT_NAME": "", "GITHUB_EVENT_PATH": ""}


def run_pipeline(event_path: str | Path, config_path: str = "repoheart.yml") -> tuple[int, str]:
    """Run the full local pipeline and return its exit code and stdout."""
    buf = StringIO()
    with (
        patch.object(sys, "stdout", buf),
        patch.dict(os.environ, _CLEAN_ENV, clear=False),
    ):
        code = main(["--event", str(event_path), "--config", config_path])
    return code, buf.getvalue()
