"""Tests for repoheart.git_ops.repo."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from repoheart.git_ops.repo import GitError, GitRepo


@pytest.fixture()
def git_repo(tmp_path: Path) -> GitRepo:
    """Create a minimal git repo with one commit and return a GitRepo for it."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    run = lambda *cmd: subprocess.run(  # noqa: E731
        list(cmd), cwd=tmp_path, check=True, capture_output=True, env=env
    )
    run("git", "init", "-b", "main")
    run("git", "config", "user.email", "test@example.com")
    run("git", "config", "user.name", "Test User")
    (tmp_path / "README.md").write_text("# Test\n", encoding="utf-8")
    run("git", "add", ".")
    run("git", "commit", "-m", "init")
    return GitRepo(repo_path=tmp_path)


def test_rev_parse_resolves_head(git_repo: GitRepo) -> None:
    sha = git_repo.rev_parse("HEAD")
    assert len(sha) == 40
    assert sha.isalnum()


def test_current_branch_returns_main(git_repo: GitRepo) -> None:
    branch = git_repo.current_branch()
    assert branch == "main"


def test_invalid_command_raises_git_error(git_repo: GitRepo) -> None:
    with pytest.raises(GitError):
        git_repo._run("not-a-valid-subcommand")


def test_list_changed_files_after_change(git_repo: GitRepo, tmp_path: Path) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    base_sha = git_repo.rev_parse("HEAD")
    (tmp_path / "new_file.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "add file"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        env=env,
    )
    changed = git_repo.list_changed_files(base_sha, "HEAD")
    assert "new_file.py" in changed


def test_get_diff_returns_diff_output(git_repo: GitRepo, tmp_path: Path) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    base_sha = git_repo.rev_parse("HEAD")
    (tmp_path / "README.md").write_text("# Updated\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "update readme"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        env=env,
    )
    diff = git_repo.get_diff(base_sha, "HEAD")
    assert "diff --git" in diff


def test_get_merge_base(git_repo: GitRepo, tmp_path: Path) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    base_sha = git_repo.rev_parse("HEAD")
    (tmp_path / "feature.py").write_text("y = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "feature"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        env=env,
    )
    head_sha = git_repo.rev_parse("HEAD")
    merge_base = git_repo.get_merge_base(base_sha, head_sha)
    assert len(merge_base) == 40


def test_create_branch_succeeds(git_repo: GitRepo) -> None:
    head = git_repo.rev_parse("HEAD")
    git_repo.create_branch("feature/test", head)
    branch = git_repo.current_branch()
    assert branch == "feature/test"


def test_create_branch_twice_raises_git_error(git_repo: GitRepo) -> None:
    head = git_repo.rev_parse("HEAD")
    git_repo.create_branch("my-branch", head)
    with pytest.raises(GitError):
        git_repo.create_branch("my-branch", head)


def test_commit_returns_sha(git_repo: GitRepo, tmp_path: Path) -> None:
    (tmp_path / "commit_test.txt").write_text("hello\n", encoding="utf-8")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    # Patch subprocess.run to inject env when calling git commit
    original_run = subprocess.run

    def patched_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[0] == "git" and "commit" in cmd:
            kwargs["env"] = env  # type: ignore[assignment]
        return original_run(cmd, **kwargs)  # type: ignore[return-value]

    import unittest.mock

    with unittest.mock.patch("subprocess.run", side_effect=patched_run):
        sha = git_repo.commit("test commit", ["commit_test.txt"])
    assert len(sha) == 40
