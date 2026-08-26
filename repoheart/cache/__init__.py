"""Cache package — optional artifact cache backends for Phase 5.

Usage:
    from repoheart.cache import make_cache
    cache = make_cache(config.scale.cache_backend, git_repo)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from repoheart.cache.actions import ActionsCacheBackend
from repoheart.cache.backend import CacheBackend, NullCacheBackend
from repoheart.cache.branch import BranchCacheBackend

if TYPE_CHECKING:
    from repoheart.git_ops.repo import GitRepo


def make_cache(
    backend_name: str,
    git_repo: GitRepo | None = None,
) -> CacheBackend:
    """Instantiate the correct CacheBackend from config.scale.cache_backend."""
    if backend_name == "actions":
        return ActionsCacheBackend()
    if backend_name == "branch" and git_repo is not None:
        return BranchCacheBackend(git_repo)
    return NullCacheBackend()


__all__ = [
    "CacheBackend",
    "NullCacheBackend",
    "ActionsCacheBackend",
    "BranchCacheBackend",
    "make_cache",
]
