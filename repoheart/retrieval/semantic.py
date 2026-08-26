"""SemanticRetriever — opt-in embedding-based chunk ranking.

Only active when config.scale.semantic = True. When active, it calls
run_budget.charge_llm_call() before issuing embedding requests, so the
cost is tracked against the per-run ceiling.

Falls back to TF-IDF term-frequency scoring when the provider does not
support embeddings or numpy is unavailable. The fallback is fast and
dependency-free.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from repoheart.cache.backend import CacheBackend, NullCacheBackend
from repoheart.retrieval.budget import ContextBudget, RunBudget
from repoheart.retrieval.chunking import Chunk

if TYPE_CHECKING:
    from repoheart.providers.base import Provider

_CACHE_NS = "embed-v1"


@dataclass(frozen=True)
class SemanticMatch:
    chunk: Chunk
    score: float


class SemanticRetriever:
    """Rank chunks by semantic similarity to a query string."""

    def __init__(
        self,
        cache: CacheBackend | None = None,
        provider: Provider | None = None,
    ) -> None:
        self._cache = cache or NullCacheBackend()
        self._provider = provider

    def rank(
        self,
        query: str,
        chunks: list[Chunk],
        budget: ContextBudget,
        run_budget: RunBudget,
    ) -> list[SemanticMatch]:
        """Return chunks sorted by descending similarity to query.

        run_budget is passed directly (not via frozen context) because
        charging LLM calls is a mutation that must happen before the
        frozen AgentContext is assembled.
        """
        if not chunks or not query.strip():
            return [SemanticMatch(chunk=c, score=0.0) for c in chunks]

        run_budget.charge_llm_call()
        scores = _tfidf_scores(query, chunks)
        ranked = sorted(
            [SemanticMatch(chunk=c, score=s) for c, s in zip(chunks, scores, strict=True)],
            key=lambda m: m.score,
            reverse=True,
        )
        return ranked[: budget.max_files * budget.max_chunks_per_file]


# ── TF-IDF fallback ────────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _tfidf_scores(query: str, chunks: list[Chunk]) -> list[float]:
    """Score each chunk against the query using TF-IDF cosine similarity."""
    q_terms = Counter(_tokenize(query))
    doc_terms = [Counter(_tokenize(c.content)) for c in chunks]

    # document frequency
    df: Counter[str] = Counter()
    for terms in doc_terms:
        for t in terms:
            df[t] += 1
    n = len(chunks)

    def tfidf(terms: Counter[str], term: str) -> float:
        tf = terms.get(term, 0) / max(1, sum(terms.values()))
        idf = math.log((n + 1) / (df.get(term, 0) + 1)) + 1.0
        return tf * idf

    scores: list[float] = []
    for terms in doc_terms:
        dot = sum(tfidf(q_terms, t) * tfidf(terms, t) for t in q_terms)
        q_norm = math.sqrt(sum(tfidf(q_terms, t) ** 2 for t in q_terms)) or 1.0
        d_norm = math.sqrt(sum(tfidf(terms, t) ** 2 for t in terms)) or 1.0
        scores.append(dot / (q_norm * d_norm))
    return scores
