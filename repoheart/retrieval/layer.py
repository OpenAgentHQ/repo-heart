"""RetrievalLayer — cheapest-first retrieval pipeline for Phase 5.

Orchestrates: structural → lexical → (semantic) retrieval, then ranks,
deduplicates, and truncates to the ContextBudget.

Called once per agent from Orchestrator._build_context(). Returns a frozen
RetrievalContext that is embedded in AgentContext.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass

from repoheart.repo_access.reader import FileContent, RepoReader
from repoheart.retrieval.budget import BudgetExceededError, RunBudget
from repoheart.retrieval.chunking import Chunk, FileChunker
from repoheart.retrieval.lexical import LexicalMatch, LexicalRetriever
from repoheart.retrieval.semantic import SemanticMatch, SemanticRetriever
from repoheart.retrieval.structural import StructuralRetriever, Symbol, SymbolGraph


@dataclass(frozen=True)
class RetrievalQuery:
    """What the orchestrator asks the retrieval layer to find."""

    terms: list[str]
    anchor_files: list[str]
    language_hint: str = ""
    max_chars: int = 20_000


@dataclass(frozen=True)
class RetrievalContext:
    """Frozen result of one retrieval call; placed inside AgentContext."""

    chunks: list[Chunk]
    symbols: list[Symbol]
    lexical_matches: list[LexicalMatch]
    files_consulted: list[str]
    budget_used_chars: int
    budget_limit_chars: int


class RetrievalLayer:
    """Execute the cheapest-first retrieval pipeline."""

    def __init__(
        self,
        reader: RepoReader,
        structural: StructuralRetriever,
        lexical: LexicalRetriever,
        chunker: FileChunker,
        semantic: SemanticRetriever | None = None,
    ) -> None:
        self._reader = reader
        self._structural = structural
        self._lexical = lexical
        self._chunker = chunker
        self._semantic = semantic

    def retrieve(
        self,
        query: RetrievalQuery,
        run_budget: RunBudget,
    ) -> RetrievalContext:
        """Run retrieval pipeline; return frozen context within budget.

        Raises BudgetExceededError if runtime ceiling is already hit before
        retrieval begins (caller should catch and log).
        """
        run_budget.check_runtime()

        ctx_budget = run_budget.to_context_budget(
            max_tokens=query.max_chars,
            priority=query.anchor_files,
        )

        # 1. Read anchor files (changed files already known)
        anchor_contents = self._reader.read_files(
            query.anchor_files,
            run_budget,
            priority_prefixes=query.anchor_files,
        )

        # 2. Lexical search for related files
        lex_matches = self._lexical.search(
            query.terms,
            ctx_budget,
            in_memory_files=anchor_contents,
        )
        anchor_paths = {f.path for f in anchor_contents}
        extra_paths = [m.file for m in lex_matches if m.file not in anchor_paths]

        extra_contents: list[FileContent] = []
        with contextlib.suppress(BudgetExceededError):
            extra_contents = self._reader.read_files(extra_paths, run_budget)

        all_contents = anchor_contents + extra_contents

        # 3. Structural analysis
        symbol_graph: SymbolGraph
        try:
            symbol_graph = self._structural.extract(all_contents, ctx_budget)
        except Exception:
            symbol_graph = SymbolGraph(symbols=[], files_analyzed=[], content_hash="")

        # 4. Chunk all files
        all_chunks: list[Chunk] = []
        for fc in all_contents:
            all_chunks.extend(self._chunker.chunk(fc, ctx_budget))

        # 5. Semantic reranking (opt-in)
        if self._semantic is not None and all_chunks:
            query_text = " ".join(query.terms)
            try:
                ranked: list[SemanticMatch] = self._semantic.rank(
                    query_text, all_chunks, ctx_budget, run_budget
                )
                all_chunks = [m.chunk for m in ranked]
            except BudgetExceededError:
                pass

        # 6. Dedup + truncate
        deduped = _dedup_chunks(all_chunks)
        final_chunks, used_chars = _truncate_to_budget(deduped, query.max_chars)

        return RetrievalContext(
            chunks=final_chunks,
            symbols=symbol_graph.symbols,
            lexical_matches=lex_matches,
            files_consulted=[f.path for f in all_contents],
            budget_used_chars=used_chars,
            budget_limit_chars=query.max_chars,
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _dedup_chunks(chunks: list[Chunk]) -> list[Chunk]:
    """Remove chunks with heavily overlapping line ranges in the same file."""
    seen: set[tuple[str, int]] = set()
    result: list[Chunk] = []
    for chunk in chunks:
        bucket = (chunk.file, chunk.start_line // 50)
        if bucket not in seen:
            seen.add(bucket)
            result.append(chunk)
    return result


def _truncate_to_budget(
    chunks: list[Chunk],
    max_chars: int,
) -> tuple[list[Chunk], int]:
    """Keep chunks until max_chars is reached; return (kept, total_chars_used)."""
    kept: list[Chunk] = []
    total = 0
    for chunk in chunks:
        if total + chunk.char_count > max_chars:
            break
        kept.append(chunk)
        total += chunk.char_count
    return kept, total
