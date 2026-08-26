"""StructuralRetriever — extract a symbol graph from source files.

Tries tree-sitter when available (optional dependency); falls back to a
regex-based approximation that handles Python class/function definitions.
Results are cached by content hash so repeated runs are free.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from repoheart.cache.backend import CacheBackend, NullCacheBackend
from repoheart.repo_access.reader import FileContent
from repoheart.retrieval.budget import ContextBudget

_CACHE_NS = "structural-v1"


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    file: str
    line: int


@dataclass(frozen=True)
class SymbolGraph:
    symbols: list[Symbol]
    files_analyzed: list[str]
    content_hash: str


class StructuralRetriever:
    """Extract symbols from source files with optional cache backing."""

    def __init__(self, cache: CacheBackend | None = None) -> None:
        self._cache = cache or NullCacheBackend()

    def extract(
        self,
        files: list[FileContent],
        budget: ContextBudget,
    ) -> SymbolGraph:
        """Extract a symbol graph from at most budget.max_files files."""
        sliced = files[: budget.max_files] if budget.max_files else files
        if not sliced:
            return SymbolGraph(symbols=[], files_analyzed=[], content_hash="")

        combined = "".join(f.content_hash for f in sliced)
        content_hash = hashlib.sha256(combined.encode()).hexdigest()
        cache_key = CacheBackend.make_key(_CACHE_NS, content_hash)

        cached: Any = self._cache.get(cache_key)
        if cached is not None:
            return _graph_from_dict(cached)

        symbols: list[Symbol] = []
        for fc in sliced:
            symbols.extend(_extract_file(fc))

        graph = SymbolGraph(
            symbols=symbols,
            files_analyzed=[f.path for f in sliced],
            content_hash=content_hash,
        )
        self._cache.put(cache_key, _graph_to_dict(graph))
        return graph


# ── Symbol extraction ──────────────────────────────────────────────────────────

_PY_DEF_RE = re.compile(r"^(?:async\s+)?def\s+(\w+)", re.MULTILINE)
_PY_CLASS_RE = re.compile(r"^class\s+(\w+)", re.MULTILINE)


def _extract_file(fc: FileContent) -> list[Symbol]:
    try:
        return _extract_tree_sitter(fc)
    except Exception:
        return _extract_regex(fc)


def _extract_tree_sitter(fc: FileContent) -> list[Symbol]:
    import tree_sitter  # noqa: F401
    raise ImportError("tree-sitter extraction not yet wired")


def _extract_regex(fc: FileContent) -> list[Symbol]:
    symbols: list[Symbol] = []
    for i, line in enumerate(fc.content.splitlines(), 1):
        stripped = line.lstrip()
        if m := re.match(r"^(?:async\s+)?def\s+(\w+)", stripped):
            symbols.append(Symbol(name=m.group(1), kind="function", file=fc.path, line=i))
        elif m := re.match(r"^class\s+(\w+)", stripped):
            symbols.append(Symbol(name=m.group(1), kind="class", file=fc.path, line=i))
    return symbols


# ── Serialisation helpers ──────────────────────────────────────────────────────

def _graph_to_dict(graph: SymbolGraph) -> dict[str, Any]:
    return {
        "symbols": [
            {"name": s.name, "kind": s.kind, "file": s.file, "line": s.line}
            for s in graph.symbols
        ],
        "files_analyzed": list(graph.files_analyzed),
        "content_hash": graph.content_hash,
    }


def _graph_from_dict(d: dict[str, Any]) -> SymbolGraph:
    raw_symbols: list[dict[str, Any]] = d.get("symbols", [])
    symbols = [
        Symbol(
            name=str(s["name"]),
            kind=str(s["kind"]),
            file=str(s["file"]),
            line=int(s["line"]),
        )
        for s in raw_symbols
    ]
    raw_files: list[str] = d.get("files_analyzed", [])
    return SymbolGraph(
        symbols=symbols,
        files_analyzed=raw_files,
        content_hash=str(d.get("content_hash", "")),
    )
