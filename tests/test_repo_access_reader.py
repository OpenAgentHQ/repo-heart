"""Tests for repoheart.repo_access.reader."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from repoheart.config.schema import LimitsConfig
from repoheart.repo_access.reader import FileContent, RepoReader, _prioritize
from repoheart.retrieval.budget import RunBudget


def _budget(files: int = 100, runtime: int = 600) -> RunBudget:
    return RunBudget(
        limits=LimitsConfig(max_llm_calls=100, max_files_read=files, max_runtime_seconds=runtime)
    )


def _tmp_repo(files: dict[str, str]) -> Path:
    tmp = Path(tempfile.mkdtemp())
    for rel_path, content in files.items():
        abs_path = tmp / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")
    return tmp


class TestRepoReader:
    def test_read_file_returns_content(self) -> None:
        root = _tmp_repo({"foo.py": "hello world"})
        r = RepoReader(root)
        fc = r.read_file("foo.py", _budget())
        assert fc is not None
        assert fc.content == "hello world"
        assert fc.path == "foo.py"
        assert len(fc.content_hash) == 64

    def test_read_file_missing_returns_none(self) -> None:
        root = _tmp_repo({})
        r = RepoReader(root)
        fc = r.read_file("does_not_exist.py", _budget())
        assert fc is None

    def test_read_file_charges_budget(self) -> None:
        root = _tmp_repo({"a.py": "x"})
        r = RepoReader(root)
        budget = _budget(files=1)
        r.read_file("a.py", budget)
        assert budget._files_read == 1

    def test_read_file_returns_none_when_budget_exhausted(self) -> None:
        root = _tmp_repo({"a.py": "x", "b.py": "y"})
        r = RepoReader(root)
        budget = _budget(files=1)
        r.read_file("a.py", budget)
        # second read should return None (budget exceeded)
        fc = r.read_file("b.py", budget)
        assert fc is None

    def test_read_files_stops_at_budget(self) -> None:
        root = _tmp_repo({"a.py": "a", "b.py": "b", "c.py": "c"})
        r = RepoReader(root)
        result = r.read_files(["a.py", "b.py", "c.py"], _budget(files=2))
        assert len(result) == 2

    def test_read_files_priority_order(self) -> None:
        root = _tmp_repo({"src/a.py": "a", "tests/b.py": "b", "src/c.py": "c"})
        r = RepoReader(root)
        result = r.read_files(
            ["tests/b.py", "src/a.py", "src/c.py"],
            _budget(files=10),
            priority_prefixes=["src/"],
        )
        paths = [fc.path for fc in result]
        # src/ files should come before tests/
        assert paths.index("src/a.py") < paths.index("tests/b.py")

    def test_read_files_empty_list(self) -> None:
        root = _tmp_repo({})
        r = RepoReader(root)
        assert r.read_files([], _budget()) == []

    def test_read_files_stops_on_runtime_exceeded(self) -> None:
        import time
        root = _tmp_repo({"a.py": "a"})
        r = RepoReader(root)
        budget = _budget(runtime=0)
        time.sleep(0.01)
        result = r.read_files(["a.py"], budget)
        assert result == []

    def test_file_content_frozen(self) -> None:
        fc = FileContent(path="x.py", content="y", size_bytes=1, content_hash="abc")
        with pytest.raises((AttributeError, TypeError)):
            fc.path = "other"  # type: ignore[misc]

    def test_list_files_fallback(self) -> None:
        root = _tmp_repo({"a.py": "a", "b.txt": "b"})
        r = RepoReader(root)
        files = r.list_files()
        # should include at least the .py file
        assert any("a.py" in f for f in files)

    def test_list_files_extension_filter(self) -> None:
        root = _tmp_repo({"a.py": "a", "b.txt": "b", "c.py": "c"})
        r = RepoReader(root)
        files = r.list_files(extensions=[".py"])
        assert all(f.endswith(".py") for f in files)
        assert not any(f.endswith(".txt") for f in files)


class TestPrioritize:
    def test_priority_first(self) -> None:
        paths = ["b.py", "a.py", "c.py"]
        result = _prioritize(paths, ["a"])
        assert result[0] == "a.py"

    def test_empty_prefixes_preserves_order(self) -> None:
        paths = ["x.py", "y.py"]
        assert _prioritize(paths, []) == paths

    def test_no_match_returns_original_order(self) -> None:
        paths = ["x.py", "y.py"]
        result = _prioritize(paths, ["z"])
        assert result == paths
