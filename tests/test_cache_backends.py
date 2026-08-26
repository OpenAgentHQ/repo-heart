"""Tests for repoheart.cache backends."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock

from repoheart.cache import make_cache
from repoheart.cache.actions import ActionsCacheBackend
from repoheart.cache.backend import CacheBackend, NullCacheBackend
from repoheart.cache.branch import BranchCacheBackend


class TestNullCacheBackend:
    def test_get_always_none(self) -> None:
        c = NullCacheBackend()
        assert c.get("any-key") is None

    def test_put_noop(self) -> None:
        c = NullCacheBackend()
        c.put("key", {"data": 123})
        assert c.get("key") is None

    def test_backend_name(self) -> None:
        assert NullCacheBackend().backend_name() == "null"

    def test_make_key_deterministic(self) -> None:
        k1 = CacheBackend.make_key("ns", "a", "b")
        k2 = CacheBackend.make_key("ns", "a", "b")
        assert k1 == k2

    def test_make_key_differs_by_namespace(self) -> None:
        k1 = CacheBackend.make_key("ns1", "a")
        k2 = CacheBackend.make_key("ns2", "a")
        assert k1 != k2


class TestActionsCacheBackend:
    def _backend_with_tmp(self) -> tuple[ActionsCacheBackend, str]:
        tmp = tempfile.mkdtemp()
        b = ActionsCacheBackend()
        b._cache_dir = tmp
        return b, tmp

    def test_get_miss(self) -> None:
        b, _ = self._backend_with_tmp()
        assert b.get("missing-key") is None

    def test_put_and_get_roundtrip(self) -> None:
        b, _ = self._backend_with_tmp()
        b.put("mykey", {"x": 42})
        result = b.get("mykey")
        assert result == {"x": 42}

    def test_put_silently_swallows_oserror(self) -> None:
        b = ActionsCacheBackend()
        b._cache_dir = "/nonexistent/path/that/cannot/be/created"
        # should not raise
        b.put("k", {"v": 1})

    def test_get_silently_swallows_corrupt_json(self) -> None:
        b, tmp = self._backend_with_tmp()
        key_path = b._key_path("badkey")
        os.makedirs(tmp, exist_ok=True)
        with open(key_path, "w") as f:
            f.write("not-json")
        assert b.get("badkey") is None

    def test_backend_name(self) -> None:
        assert ActionsCacheBackend().backend_name() == "actions"

    def test_no_cache_dir_get_returns_none(self) -> None:
        b = ActionsCacheBackend()
        b._cache_dir = ""
        assert b.get("k") is None

    def test_no_cache_dir_put_noop(self) -> None:
        b = ActionsCacheBackend()
        b._cache_dir = ""
        b.put("k", "v")  # should not raise


class TestBranchCacheBackend:
    def _mock_git(self, stdout: str = "", returncode: int = 0) -> MagicMock:
        git = MagicMock()
        result = MagicMock()
        result.returncode = returncode
        result.stdout = stdout
        git._run.return_value = result
        return git

    def test_get_miss_on_nonzero_returncode(self) -> None:
        b = BranchCacheBackend(self._mock_git(returncode=1))
        assert b.get("key") is None

    def test_get_hit(self) -> None:
        import json
        data = {"symbols": []}
        b = BranchCacheBackend(self._mock_git(stdout=json.dumps(data)))
        assert b.get("key") == data

    def test_put_is_noop(self) -> None:
        b = BranchCacheBackend(self._mock_git())
        b.put("key", {"v": 1})  # must not raise, writes nothing
        b._git._run.assert_not_called()

    def test_backend_name(self) -> None:
        b = BranchCacheBackend(self._mock_git())
        assert b.backend_name() == "branch"


class TestMakeCache:
    def test_actions_backend(self) -> None:
        c = make_cache("actions")
        assert isinstance(c, ActionsCacheBackend)

    def test_null_for_none(self) -> None:
        c = make_cache("none")
        assert isinstance(c, NullCacheBackend)

    def test_null_for_unknown(self) -> None:
        c = make_cache("redis")
        assert isinstance(c, NullCacheBackend)

    def test_branch_without_git_repo_falls_back(self) -> None:
        c = make_cache("branch", git_repo=None)
        assert isinstance(c, NullCacheBackend)

    def test_branch_with_git_repo(self) -> None:
        mock_git = MagicMock()
        c = make_cache("branch", git_repo=mock_git)
        assert isinstance(c, BranchCacheBackend)
