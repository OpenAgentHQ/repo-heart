"""Tests for repoheart.retrieval.structural."""

from __future__ import annotations

from repoheart.cache.backend import NullCacheBackend
from repoheart.repo_access.reader import FileContent
from repoheart.retrieval.budget import ContextBudget
from repoheart.retrieval.structural import (
    StructuralRetriever,
    Symbol,
    SymbolGraph,
    _extract_regex,
    _graph_from_dict,
    _graph_to_dict,
)


def _fc(path: str, content: str) -> FileContent:
    import hashlib
    h = hashlib.sha256(content.encode()).hexdigest()
    return FileContent(path=path, content=content, size_bytes=len(content), content_hash=h)


def _budget(max_files: int = 100) -> ContextBudget:
    return ContextBudget(max_tokens=10_000, max_files=max_files)


class TestExtractRegex:
    def test_extracts_function(self) -> None:
        fc = _fc("a.py", "def foo():\n    pass\n")
        syms = _extract_regex(fc)
        assert any(s.name == "foo" and s.kind == "function" for s in syms)

    def test_extracts_class(self) -> None:
        fc = _fc("a.py", "class Bar:\n    pass\n")
        syms = _extract_regex(fc)
        assert any(s.name == "Bar" and s.kind == "class" for s in syms)

    def test_extracts_async_def(self) -> None:
        fc = _fc("a.py", "async def baz():\n    pass\n")
        syms = _extract_regex(fc)
        assert any(s.name == "baz" and s.kind == "function" for s in syms)

    def test_correct_line_number(self) -> None:
        fc = _fc("a.py", "x = 1\ndef qux():\n    pass\n")
        syms = _extract_regex(fc)
        qux = next(s for s in syms if s.name == "qux")
        assert qux.line == 2

    def test_empty_file(self) -> None:
        fc = _fc("empty.py", "")
        assert _extract_regex(fc) == []


class TestStructuralRetriever:
    def test_empty_files_returns_empty_graph(self) -> None:
        r = StructuralRetriever(NullCacheBackend())
        graph = r.extract([], _budget())
        assert graph.symbols == []
        assert graph.files_analyzed == []

    def test_extract_returns_symbols(self) -> None:
        fc = _fc("m.py", "def hello():\n    pass\nclass World:\n    pass\n")
        r = StructuralRetriever(NullCacheBackend())
        graph = r.extract([fc], _budget())
        names = {s.name for s in graph.symbols}
        assert "hello" in names
        assert "World" in names

    def test_budget_max_files_respected(self) -> None:
        files = [_fc(f"f{i}.py", f"def fn{i}(): pass\n") for i in range(5)]
        r = StructuralRetriever(NullCacheBackend())
        graph = r.extract(files, _budget(max_files=2))
        assert len(graph.files_analyzed) == 2

    def test_cache_hit_skips_extraction(self) -> None:
        from unittest.mock import MagicMock
        cache = MagicMock()
        cached_graph = {
            "symbols": [{"name": "cached_fn", "kind": "function", "file": "x.py", "line": 1}],
            "files_analyzed": ["x.py"],
            "content_hash": "abc",
        }
        cache.get.return_value = cached_graph

        fc = _fc("x.py", "def real_fn(): pass\n")
        r = StructuralRetriever(cache)
        graph = r.extract([fc], _budget())
        # Should return cached result, not the real extraction
        assert any(s.name == "cached_fn" for s in graph.symbols)
        cache.put.assert_not_called()

    def test_cache_miss_populates_cache(self) -> None:
        from unittest.mock import MagicMock
        cache = MagicMock()
        cache.get.return_value = None

        fc = _fc("y.py", "def fn(): pass\n")
        r = StructuralRetriever(cache)
        r.extract([fc], _budget())
        cache.put.assert_called_once()


class TestSerialisation:
    def test_roundtrip(self) -> None:
        graph = SymbolGraph(
            symbols=[Symbol(name="foo", kind="function", file="a.py", line=3)],
            files_analyzed=["a.py"],
            content_hash="deadbeef",
        )
        d = _graph_to_dict(graph)
        restored = _graph_from_dict(d)
        assert restored.content_hash == "deadbeef"
        assert restored.symbols[0].name == "foo"
