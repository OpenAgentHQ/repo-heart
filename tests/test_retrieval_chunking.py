"""Tests for repoheart.retrieval.chunking."""

from __future__ import annotations

import hashlib

from repoheart.repo_access.reader import FileContent
from repoheart.retrieval.budget import ContextBudget
from repoheart.retrieval.chunking import FileChunker


def _fc(path: str, content: str) -> FileContent:
    h = hashlib.sha256(content.encode()).hexdigest()
    return FileContent(path=path, content=content, size_bytes=len(content), content_hash=h)


def _budget(max_chunks: int = 20) -> ContextBudget:
    return ContextBudget(max_tokens=100_000, max_files=100, max_chunks_per_file=max_chunks)


class TestFileChunker:
    def test_single_line_file_produces_one_chunk(self) -> None:
        fc = _fc("a.py", "x = 1")
        chunks = FileChunker().chunk(fc, _budget())
        assert len(chunks) == 1
        assert chunks[0].content == "x = 1"

    def test_empty_file_produces_no_chunks(self) -> None:
        fc = _fc("empty.py", "")
        assert FileChunker().chunk(fc, _budget()) == []

    def test_large_file_produces_multiple_chunks(self) -> None:
        # ~5000 chars → should produce multiple chunks at default 2000-char limit
        lines = [f"x_{i} = {i}  # line comment" for i in range(200)]
        fc = _fc("big.py", "\n".join(lines))
        chunks = FileChunker().chunk(fc, _budget())
        assert len(chunks) > 1

    def test_max_chunks_per_file_respected(self) -> None:
        lines = "\n".join(f"x_{i} = {i}" for i in range(500))
        fc = _fc("big.py", lines)
        chunks = FileChunker().chunk(fc, _budget(max_chunks=3))
        assert len(chunks) <= 3

    def test_chunk_index_monotonically_increasing(self) -> None:
        lines = "\n".join(f"line_{i}" for i in range(200))
        fc = _fc("f.py", lines)
        chunks = FileChunker().chunk(fc, _budget())
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_chunk_start_line_positive(self) -> None:
        fc = _fc("a.py", "a\nb\nc\nd\ne\n")
        chunks = FileChunker(chunk_chars=3).chunk(fc, _budget())
        for c in chunks:
            assert c.start_line >= 1

    def test_char_count_matches_content(self) -> None:
        fc = _fc("a.py", "hello world")
        chunks = FileChunker().chunk(fc, _budget())
        for c in chunks:
            assert c.char_count == len(c.content)

    def test_chunk_frozen(self) -> None:
        import pytest
        fc = _fc("a.py", "x = 1")
        chunks = FileChunker().chunk(fc, _budget())
        with pytest.raises((AttributeError, TypeError)):
            chunks[0].file = "other"  # type: ignore[misc]

    def test_file_path_preserved_in_chunks(self) -> None:
        fc = _fc("subdir/module.py", "def foo(): pass\n")
        chunks = FileChunker().chunk(fc, _budget())
        assert all(c.file == "subdir/module.py" for c in chunks)
