"""Tests for repoheart.retrieval.layer."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from repoheart.cache.backend import NullCacheBackend
from repoheart.config.schema import LimitsConfig
from repoheart.repo_access.reader import RepoReader
from repoheart.retrieval.budget import BudgetExceededError, RunBudget
from repoheart.retrieval.chunking import FileChunker
from repoheart.retrieval.layer import (
    RetrievalLayer,
    RetrievalQuery,
    _dedup_chunks,
    _truncate_to_budget,
)
from repoheart.retrieval.lexical import LexicalRetriever
from repoheart.retrieval.structural import StructuralRetriever


def _limits(files: int = 50, llm: int = 20, runtime: int = 600) -> LimitsConfig:
    return LimitsConfig(max_llm_calls=llm, max_files_read=files, max_runtime_seconds=runtime)


def _budget(**kwargs: int) -> RunBudget:
    return RunBudget(limits=_limits(**kwargs))


def _tmp_repo(files: dict[str, str]) -> Path:
    tmp = Path(tempfile.mkdtemp())
    for rel_path, content in files.items():
        abs_path = tmp / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")
    return tmp


def _layer(root: Path) -> RetrievalLayer:
    return RetrievalLayer(
        reader=RepoReader(root),
        structural=StructuralRetriever(NullCacheBackend()),
        lexical=LexicalRetriever(root),
        chunker=FileChunker(),
        semantic=None,
    )


class TestRetrievalLayer:
    def test_empty_anchor_files_returns_empty_context(self) -> None:
        root = _tmp_repo({})
        layer = _layer(root)
        query = RetrievalQuery(terms=[], anchor_files=[], max_chars=10_000)
        ctx = layer.retrieve(query, _budget())
        assert ctx.chunks == []
        assert ctx.files_consulted == []

    def test_reads_anchor_files(self) -> None:
        root = _tmp_repo({"a.py": "def foo(): pass\n"})
        layer = _layer(root)
        query = RetrievalQuery(terms=["foo"], anchor_files=["a.py"], max_chars=10_000)
        ctx = layer.retrieve(query, _budget())
        assert "a.py" in ctx.files_consulted

    def test_retrieval_context_is_frozen(self) -> None:
        root = _tmp_repo({})
        layer = _layer(root)
        query = RetrievalQuery(terms=[], anchor_files=[], max_chars=1_000)
        ctx = layer.retrieve(query, _budget())
        with pytest.raises((AttributeError, TypeError)):
            ctx.budget_used_chars = 999  # type: ignore[misc]

    def test_budget_limit_chars_matches_query(self) -> None:
        root = _tmp_repo({})
        layer = _layer(root)
        query = RetrievalQuery(terms=[], anchor_files=[], max_chars=5_000)
        ctx = layer.retrieve(query, _budget())
        assert ctx.budget_limit_chars == 5_000

    def test_semantic_skipped_when_none(self) -> None:
        root = _tmp_repo({"b.py": "x = 1\n"})
        layer = _layer(root)  # semantic=None
        query = RetrievalQuery(terms=["x"], anchor_files=["b.py"], max_chars=10_000)
        budget = _budget(llm=0)  # zero LLM calls allowed
        # should not raise even though llm calls=0 (semantic disabled)
        ctx = layer.retrieve(query, budget)
        assert ctx is not None

    def test_missing_anchor_file_gracefully_skipped(self) -> None:
        root = _tmp_repo({})
        layer = _layer(root)
        query = RetrievalQuery(terms=[], anchor_files=["nonexistent.py"], max_chars=10_000)
        ctx = layer.retrieve(query, _budget())
        assert ctx.files_consulted == []

    def test_symbols_populated_from_anchor_files(self) -> None:
        root = _tmp_repo({"c.py": "def bar(): pass\nclass Baz: pass\n"})
        layer = _layer(root)
        query = RetrievalQuery(terms=[], anchor_files=["c.py"], max_chars=10_000)
        ctx = layer.retrieve(query, _budget())
        names = {s.name for s in ctx.symbols}
        assert "bar" in names
        assert "Baz" in names

    def test_budget_exceeded_on_runtime(self) -> None:
        import time
        root = _tmp_repo({"d.py": "x = 1\n"})
        layer = _layer(root)
        query = RetrievalQuery(terms=[], anchor_files=["d.py"], max_chars=10_000)
        budget = _budget(runtime=0)
        time.sleep(0.01)
        with pytest.raises(BudgetExceededError):
            layer.retrieve(query, budget)


class TestDedupChunks:
    def test_dedup_same_bucket(self) -> None:
        from repoheart.retrieval.chunking import Chunk
        chunks = [
            Chunk(file="a.py", start_line=1, end_line=10, content="x", char_count=1, chunk_index=0),
            Chunk(file="a.py", start_line=5, end_line=20, content="y", char_count=1, chunk_index=1),
        ]
        result = _dedup_chunks(chunks)
        assert len(result) == 1

    def test_dedup_different_files(self) -> None:
        from repoheart.retrieval.chunking import Chunk
        chunks = [
            Chunk(file="a.py", start_line=1, end_line=10, content="x", char_count=1, chunk_index=0),
            Chunk(file="b.py", start_line=1, end_line=10, content="y", char_count=1, chunk_index=0),
        ]
        result = _dedup_chunks(chunks)
        assert len(result) == 2


class TestTruncateToBudget:
    def test_keeps_within_budget(self) -> None:
        from repoheart.retrieval.chunking import Chunk
        chunks = [
            Chunk(file="a.py", start_line=1, end_line=5, content="abc",
                  char_count=3, chunk_index=0),
            Chunk(file="a.py", start_line=6, end_line=10, content="de",
                  char_count=2, chunk_index=1),
        ]
        kept, used = _truncate_to_budget(chunks, max_chars=4)
        assert len(kept) == 1
        assert used == 3

    def test_all_fit(self) -> None:
        from repoheart.retrieval.chunking import Chunk
        chunks = [
            Chunk(file="a.py", start_line=1, end_line=5, content="ab", char_count=2, chunk_index=0),
        ]
        kept, used = _truncate_to_budget(chunks, max_chars=100)
        assert len(kept) == 1
        assert used == 2
