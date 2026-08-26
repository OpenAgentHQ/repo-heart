"""ActionsCacheBackend — reads/writes JSON files under $RUNNER_TEMP.

Gracefully degrades to a no-op when ACTIONS_CACHE_URL is absent (i.e. when
running outside GitHub Actions). Never raises on get() or put().
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from repoheart.cache.backend import CacheBackend

_PREFIX = "repoheart-v1-"


class ActionsCacheBackend(CacheBackend):
    """Cache backend that persists JSON files in the Actions runner temp dir."""

    def __init__(self) -> None:
        self._available = bool(os.environ.get("ACTIONS_CACHE_URL") or os.environ.get("RUNNER_TEMP"))
        runner_temp = os.environ.get("RUNNER_TEMP", "")
        self._cache_dir = os.path.join(runner_temp, "repoheart-cache") if runner_temp else ""

    def get(self, key: str) -> Any | None:
        if not self._cache_dir:
            return None
        try:
            path = self._key_path(key)
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return None

    def put(self, key: str, value: Any) -> None:
        if not self._cache_dir:
            return
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
            with open(self._key_path(key), "w", encoding="utf-8") as f:
                json.dump(value, f)
        except Exception:
            pass

    def backend_name(self) -> str:
        return "actions"

    def _key_path(self, key: str) -> str:
        safe = hashlib.sha256(key.encode()).hexdigest()[:32]
        return os.path.join(self._cache_dir, f"{_PREFIX}{safe}.json")
