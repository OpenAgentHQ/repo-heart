"""Regression tests: linter/secret-scan tools must be base dependencies.

The orchestrator shells out to ``ruff``, ``mypy``, and ``detect-secrets``
at runtime (see ``orchestrator/orchestrator.py``). If they only live in the
``dev`` extra, the shipped Docker image (``pip install .``) never has them
on ``PATH`` and ``CodeQualityAgent`` silently no-ops.
"""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
_REQUIRED_TOOLS = ("ruff", "mypy", "detect-secrets")


def _load_pyproject() -> dict:
    with _PYPROJECT.open("rb") as f:
        return tomllib.load(f)


def test_lint_and_secret_scan_tools_are_base_dependencies() -> None:
    data = _load_pyproject()
    dependencies = data["project"]["dependencies"]
    names = [dep.split(">=")[0].split("==")[0].strip() for dep in dependencies]
    for tool in _REQUIRED_TOOLS:
        assert tool in names, f"{tool} must be a base dependency, not dev-only"


def test_dev_extra_does_not_duplicate_base_tools() -> None:
    data = _load_pyproject()
    dev_deps = data["project"]["optional-dependencies"]["dev"]
    dev_names = [dep.split(">=")[0].split("==")[0].strip() for dep in dev_deps]
    for tool in _REQUIRED_TOOLS:
        assert tool not in dev_names


def test_lint_and_secret_scan_tools_resolve_on_path() -> None:
    for tool in _REQUIRED_TOOLS:
        assert shutil.which(tool) is not None, f"{tool} not found on PATH"
