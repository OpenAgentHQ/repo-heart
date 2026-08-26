"""Budget-aware file reader over the local workspace.

In GitHub Actions, the workspace is already present at $GITHUB_WORKSPACE
before RepoHeart runs. This module reads files from that checkout with
budget enforcement — it never initiates a new clone.

'Event-scoped' means: read only files relevant to the event (anchor =
changed_files), stopping when RunBudget.max_files_read is exhausted.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from repoheart.retrieval.budget import BudgetExceededError, RunBudget


@dataclass(frozen=True)
class FileContent:
    """Immutable snapshot of a single file's text content."""

    path: str
    content: str
    size_bytes: int
    content_hash: str


class RepoReader:
    """Budget-aware reader over the local Git workspace."""

    def __init__(self, repo_root: str | Path = ".") -> None:
        self._root = Path(repo_root)

    def read_file(self, path: str, budget: RunBudget) -> FileContent | None:
        """Read one file and charge the budget.

        Returns None (without raising) when:
          - The file does not exist or is a directory.
          - The budget ceiling has already been hit.
        """
        budget.check_runtime()
        try:
            budget.charge_files_read(1)
        except BudgetExceededError:
            return None
        abs_path = self._root / path
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, IsADirectoryError):
            return None
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        return FileContent(
            path=path,
            content=content,
            size_bytes=len(content.encode()),
            content_hash=content_hash,
        )

    def read_files(
        self,
        paths: list[str],
        budget: RunBudget,
        *,
        priority_prefixes: list[str] | None = None,
    ) -> list[FileContent]:
        """Read multiple files in priority order, stopping at budget ceiling."""
        ordered = _prioritize(paths, priority_prefixes or [])
        results: list[FileContent] = []
        for path in ordered:
            if budget.remaining_files() <= 0:
                break
            try:
                budget.check_runtime()
            except BudgetExceededError:
                break
            fc = self.read_file(path, budget)
            if fc is not None:
                results.append(fc)
        return results

    def list_files(self, extensions: list[str] | None = None) -> list[str]:
        """List tracked files in the workspace via git ls-files.

        Falls back to os.walk when git is unavailable. Never charges budget —
        this is a directory listing, not a content read.
        """
        try:
            result = subprocess.run(
                ["git", "ls-files"],
                cwd=str(self._root),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode == 0:
                files = result.stdout.strip().splitlines()
            else:
                files = _walk_files(self._root)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            files = _walk_files(self._root)

        if extensions:
            ext_set = set(extensions)
            files = [f for f in files if os.path.splitext(f)[1] in ext_set]
        return files


def _prioritize(paths: list[str], prefixes: list[str]) -> list[str]:
    """Sort paths so those matching priority prefixes come first."""
    if not prefixes:
        return list(paths)
    priority = [p for p in paths if any(p.startswith(px) for px in prefixes)]
    rest = [p for p in paths if p not in set(priority)]
    return priority + rest


def _walk_files(root: Path) -> list[str]:
    files: list[str] = []
    for dirpath, _dirs, filenames in os.walk(root):
        for filename in filenames:
            abs_path = os.path.join(dirpath, filename)
            try:
                rel = os.path.relpath(abs_path, root)
                files.append(rel)
            except ValueError:
                pass
    return files
