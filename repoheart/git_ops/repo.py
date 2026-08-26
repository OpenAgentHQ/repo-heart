"""Local git operations via subprocess.

All methods invoke the ``git`` binary directly. The class is stateless —
each method creates a fresh subprocess. The ``git`` binary is pre-installed
in the Docker image used by the GitHub Actions runner.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """Raised when a git command exits with a non-zero status."""


class GitRepo:
    """Local git repository operations.

    Args:
        repo_path: Path to the repository root. Defaults to the current
            working directory.
    """

    def __init__(self, repo_path: str | Path = ".") -> None:
        self._repo_path = Path(repo_path)

    def get_merge_base(self, sha1: str, sha2: str) -> str:
        """Return the merge-base commit SHA of two refs."""
        result = self._run("merge-base", sha1, sha2)
        return result.stdout.strip()

    def list_changed_files(self, base: str, head: str) -> list[str]:
        """Return relative paths of files changed between ``base`` and ``head``."""
        result = self._run("diff", "--name-only", base, head)
        lines = result.stdout.strip().splitlines()
        return [line for line in lines if line]

    def get_diff(self, base: str, head: str) -> str:
        """Return the unified diff between ``base`` and ``head``."""
        result = self._run("diff", base, head)
        return result.stdout

    def create_branch(self, name: str, from_ref: str) -> None:
        """Create a new branch at ``from_ref``.

        Raises:
            GitError: if the branch already exists.
        """
        self._run("checkout", "-b", name, from_ref)

    def commit(self, message: str, paths: list[str]) -> str:
        """Stage ``paths`` and create a commit.

        Returns:
            The new commit SHA.

        Note: does NOT push. Pushing is a separate, higher-risk operation
        handled in Phase 6.
        """
        if paths:
            self._run("add", "--", *paths)
        self._run("commit", "-m", message)
        result = self._run("rev-parse", "HEAD")
        return result.stdout.strip()

    def current_branch(self) -> str:
        """Return the name of the currently checked-out branch."""
        result = self._run("rev-parse", "--abbrev-ref", "HEAD")
        return result.stdout.strip()

    def rev_parse(self, ref: str) -> str:
        """Resolve a ref to a full commit SHA."""
        result = self._run("rev-parse", ref)
        return result.stdout.strip()

    def commits_between(self, base: str, head: str) -> list[str]:
        """Return one-line commit messages between ``base`` and ``head``.

        Excludes ``base`` itself (exclusive lower bound, inclusive upper bound),
        matching the behaviour of ``git log base..head``.
        """
        result = self._run("log", "--oneline", f"{base}..{head}")
        lines = result.stdout.strip().splitlines()
        return [line for line in lines if line]

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run a git command inside ``repo_path``.

        Args:
            *args: Arguments passed to ``git`` (without the ``git`` prefix).
            check: If True, raise ``GitError`` on non-zero exit.

        Raises:
            GitError: if ``check`` is True and the command fails.
        """
        cmd = ["git", *args]
        try:
            result = subprocess.run(
                cmd,
                cwd=self._repo_path,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise GitError(f"git binary not found: {exc}") from exc

        if check and result.returncode != 0:
            raise GitError(
                f"git {' '.join(args)!r} failed (exit {result.returncode}):\n"
                f"{result.stderr.strip()}"
            )

        return result
