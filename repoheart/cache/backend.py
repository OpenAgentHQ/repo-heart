"""CacheBackend ABC and NullCacheBackend.

A cache miss must never affect correctness — only speed. Implementations
must swallow all errors silently so a broken cache never aborts a run.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import Any


class CacheBackend(ABC):
    """Abstract content-addressed key/value store for derived artifacts."""

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """Return cached value or None on miss."""

    @abstractmethod
    def put(self, key: str, value: Any) -> None:
        """Store value under key. Must never raise."""

    @abstractmethod
    def backend_name(self) -> str: ...

    @staticmethod
    def make_key(namespace: str, *parts: str) -> str:
        """Build a deterministic cache key from a namespace + content parts."""
        combined = namespace + ":" + ":".join(parts)
        return hashlib.sha256(combined.encode()).hexdigest()


class NullCacheBackend(CacheBackend):
    """Always-miss cache used in tests and when cache_backend='none'."""

    def get(self, key: str) -> None:
        return None

    def put(self, key: str, value: Any) -> None:
        pass

    def backend_name(self) -> str:
        return "null"
