"""Tests for repoheart.retrieval.lexical."""

from __future__ import annotations

import hashlib

from repoheart.repo_access.reader import FileContent
from repoheart.retrieval.budget import ContextBudget
from repoheart.retrieval.lexical import LexicalMatch, LexicalRetriever, _dedup_by_file


def _budget(max_files: int = 10) -> ContextBudget:
    return ContextBudget(max_tokens=10_000, max_files=max_files)


def _fc(path: str, content: str) -> FileContent:
    h = hashlib.sha256(content.encode()).hexdigest()
    return FileContent(path=path, content=content, size_bytes=len(content), content_hash=h)


class TestLexicalRetriever:
    def test_empty_terms_returns_empty(self) -> None:
        r = LexicalRetriever(repo_root=".")
        assert r.search([], _budget()) == []

    def test_in_memory_search_finds_match(self) -> None:
        files = [
            _fc("a.py", "def foo():\n    return 42\n"),
            _fc("b.py", "x = 1\n"),
        ]
        r = LexicalRetriever(repo_root=".")
        results = r.search(["foo"], _budget(), in_memory_files=files)
        assert any(m.file == "a.py" for m in results)

    def test_in_memory_search_no_match(self) -> None:
        files = [_fc("a.py", "x = 1\n")]
        r = LexicalRetriever(repo_root=".")
        results = r.search(["nonexistent_symbol_xyz"], _budget(), in_memory_files=files)
        assert results == []

    def test_results_capped_at_budget_max_files(self) -> None:
        files = [_fc(f"f{i}.py", "def target(): pass\n") for i in range(10)]
        r = LexicalRetriever(repo_root=".")
        results = r.search(["target"], _budget(max_files=3), in_memory_files=files)
        assert len(results) <= 3

    def test_dedup_across_terms(self) -> None:
        files = [_fc("a.py", "foo bar")]
        r = LexicalRetriever(repo_root=".")
        results = r.search(["foo", "bar"], _budget(), in_memory_files=files)
        # a.py should appear only once despite matching both terms
        file_paths = [m.file for m in results]
        assert file_paths.count("a.py") == 1

    def test_rg_unavailable_falls_back_to_in_memory(self) -> None:
        files = [_fc("c.py", "import target\n")]
        r = LexicalRetriever(repo_root="/nonexistent_path_xyz")
        results = r._search_term("target", _budget(), None, files)
        assert any(m.file == "c.py" for m in results)


class TestDedupByFile:
    def test_dedup(self) -> None:
        matches = [
            LexicalMatch(file="a.py", line=1, snippet="", score=1.0),
            LexicalMatch(file="a.py", line=2, snippet="", score=1.0),
            LexicalMatch(file="b.py", line=1, snippet="", score=1.0),
        ]
        result = _dedup_by_file(matches)
        assert len(result) == 2
        assert {m.file for m in result} == {"a.py", "b.py"}

    def test_preserves_order(self) -> None:
        matches = [
            LexicalMatch(file="b.py", line=1, snippet="", score=1.0),
            LexicalMatch(file="a.py", line=1, snippet="", score=1.0),
        ]
        result = _dedup_by_file(matches)
        assert result[0].file == "b.py"
