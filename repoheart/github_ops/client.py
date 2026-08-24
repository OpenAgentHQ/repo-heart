"""GitHub REST API wrapper.

This is the only module in RepoHeart that sends HTTP requests to GitHub.
Every write method requires a ``Decision.ALLOW`` token — passing anything else
raises ``PermissionDenied``, making it structurally impossible to bypass the
Safety Gate.

Uses ``urllib.request`` from the standard library to keep the dependency list
minimal.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from repoheart.github_ops.budgeter import RateLimiter
from repoheart.observability.logger import StructuredLogger
from repoheart.safety.policy import Decision


class GitHubError(RuntimeError):
    """Raised when a GitHub API call returns a non-2xx response."""


class PermissionDenied(RuntimeError):
    """Raised when a write is attempted without ``Decision.ALLOW``."""


class GitHubClient:
    """GitHub REST API wrapper with integrated rate-limit budgeting.

    Args:
        token: GitHub personal access token (``GITHUB_TOKEN``).
        rate_limiter: Shared ``RateLimiter`` instance.
        logger: ``StructuredLogger`` for logging requests.
        base_url: Override for testing. Defaults to the GitHub REST API.
    """

    def __init__(
        self,
        token: str,
        rate_limiter: RateLimiter,
        logger: StructuredLogger,
        base_url: str = "https://api.github.com",
    ) -> None:
        self._token = token
        self._rate_limiter = rate_limiter
        self._logger = logger
        self._base_url = base_url.rstrip("/")

    # ── Read operations (no Decision required) ───────────────────────────────

    def get_issue(self, repo: str, number: int) -> dict[str, Any]:
        result: dict[str, Any] = self._get(f"/repos/{repo}/issues/{number}")
        return result

    def get_pull_request(self, repo: str, number: int) -> dict[str, Any]:
        result: dict[str, Any] = self._get(f"/repos/{repo}/pulls/{number}")
        return result

    def list_issue_labels(self, repo: str, number: int) -> list[str]:
        data = self._get(f"/repos/{repo}/issues/{number}/labels")
        if isinstance(data, list):
            return [item["name"] for item in data if isinstance(item, dict)]
        return []

    def get_issue_comments(self, repo: str, number: int) -> list[dict[str, Any]]:
        data = self._get(f"/repos/{repo}/issues/{number}/comments")
        return data if isinstance(data, list) else []

    def list_labels(self, repo: str) -> list[dict[str, Any]]:
        data = self._get(f"/repos/{repo}/labels")
        return data if isinstance(data, list) else []

    # ── Write operations (Decision.ALLOW required) ───────────────────────────

    def add_label(
        self,
        repo: str,
        number: int,
        labels: list[str],
        decision: Decision,
    ) -> None:
        self._check_write_allowed(decision)
        self._post(f"/repos/{repo}/issues/{number}/labels", {"labels": labels})

    def post_comment(
        self,
        repo: str,
        number: int,
        body: str,
        decision: Decision,
    ) -> None:
        self._check_write_allowed(decision)
        self._post(f"/repos/{repo}/issues/{number}/comments", {"body": body})

    def create_label(
        self,
        repo: str,
        name: str,
        color: str,
        decision: Decision,
    ) -> None:
        self._check_write_allowed(decision)
        self._post(f"/repos/{repo}/labels", {"name": name, "color": color})

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _check_write_allowed(self, decision: Decision) -> None:
        if decision != Decision.ALLOW:
            raise PermissionDenied(
                f"Write requires Decision.ALLOW; got {decision.value}"
            )

    def _get(self, path: str) -> Any:  # noqa: ANN401
        self._rate_limiter.acquire()
        url = self._base_url + path
        req = urllib.request.Request(url, headers=self._auth_headers())
        try:
            with urllib.request.urlopen(req) as resp:
                self._sync_rate_limit(dict(resp.headers))
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise GitHubError(
                f"GET {url} returned HTTP {exc.code}: {exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise GitHubError(f"GET {url} failed: {exc.reason}") from exc

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self._rate_limiter.acquire()
        url = self._base_url + path
        data = json.dumps(body).encode("utf-8")
        headers = {**self._auth_headers(), "Content-Type": "application/json"}
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                self._sync_rate_limit(dict(resp.headers))
                result: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                return result
        except urllib.error.HTTPError as exc:
            raise GitHubError(
                f"POST {url} returned HTTP {exc.code}: {exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise GitHubError(f"POST {url} failed: {exc.reason}") from exc

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _sync_rate_limit(self, headers: dict[str, str]) -> None:
        self._rate_limiter.update_from_headers(headers)
