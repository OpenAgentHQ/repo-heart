"""FileChunker — split file content into budget-respecting chunks.

Pure transformation: no I/O, no external dependencies, no LLM calls.

Strategy: group lines into chunks of ~chunk_chars characters, breaking
preferentially on blank lines. Never splits in the middle of a continued
indented block when avoidable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from repoheart.repo_access.reader import FileContent
from repoheart.retrieval.budget import ContextBudget


class _RawChunk(TypedDict):
    start: int
    end: int
    text: str

_DEFAULT_CHUNK_CHARS = 2_000
_DEFAULT_OVERLAP_LINES = 3


@dataclass(frozen=True)
class Chunk:
    file: str
    start_line: int
    end_line: int
    content: str
    char_count: int
    chunk_index: int


class FileChunker:
    """Split FileContent objects into overlapping Chunks."""

    def __init__(
        self,
        chunk_chars: int = _DEFAULT_CHUNK_CHARS,
        overlap_lines: int = _DEFAULT_OVERLAP_LINES,
    ) -> None:
        self._chunk_chars = chunk_chars
        self._overlap_lines = overlap_lines

    def chunk(self, fc: FileContent, budget: ContextBudget) -> list[Chunk]:
        """Return up to budget.max_chunks_per_file chunks from fc."""
        lines = fc.content.splitlines()
        if not lines:
            return []

        raw: list[_RawChunk] = _split_lines(lines, self._chunk_chars, self._overlap_lines)
        raw = raw[: budget.max_chunks_per_file]

        return [
            Chunk(
                file=fc.path,
                start_line=c["start"],
                end_line=c["end"],
                content=c["text"],
                char_count=len(c["text"]),
                chunk_index=i,
            )
            for i, c in enumerate(raw)
        ]


def _split_lines(
    lines: list[str],
    chunk_chars: int,
    overlap_lines: int,
) -> list[_RawChunk]:
    """Group lines into chunks of approximately chunk_chars characters."""
    chunks: list[_RawChunk] = []
    current: list[str] = []
    current_chars = 0
    start = 1  # 1-based line number

    for i, line in enumerate(lines, 1):
        current.append(line)
        current_chars += len(line) + 1  # +1 for newline

        is_blank = not line.strip()
        over_limit = current_chars >= chunk_chars

        if (is_blank and current_chars >= chunk_chars // 2) or over_limit:
            text = "\n".join(current)
            chunks.append({"start": start, "end": i, "text": text})
            overlap = current[-overlap_lines:] if overlap_lines else []
            start = i - len(overlap) + 1
            current = list(overlap)
            current_chars = sum(len(ln) + 1 for ln in current)

    if current and any(ln.strip() for ln in current):
        text = "\n".join(current)
        chunks.append({"start": start, "end": start + len(current) - 1, "text": text})

    return chunks
