"""BranchCacheBackend — reads cache artifacts from a dedicated git branch.

In Phase 5, this backend is read-only. Writing to the cache branch requires
a COMMIT action which must go through the Safety Gate; that write path is
deferred to Phase 6.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from repoheart.cache.backend import CacheBackend

if TYPE_CHECKING:
    from repoheart.git_ops.repo import GitRepo

_CACHE_BRANCH = "repoheart-cache"


class BranchCacheBackend(CacheBackend):
    """Reads cache artifacts stored as JSON files on a dedicated git branch."""

    def __init__(self, git_repo: GitRepo) -> None:
        self._git = git_repo

    def get(self, key: str) -> Any | None:
        key_file = self._key_file(key)
        try:
            result = self._git._run("show", f"{_CACHE_BRANCH}:{key_file}", check=False)
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout)
        except Exception:
            pass
        return None

    def put(self, key: str, value: Any) -> None:
        pass

    def backend_name(self) -> str:
        return "branch"

    @staticmethod
    def _key_file(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()[:32] + ".json"
