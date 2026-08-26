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
import urllib.parse
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

    def search_issues(
        self,
        repo: str,
        query: str,
        state: str = "open",
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Search issues in a repo using GitHub's search API."""
        qs = urllib.parse.urlencode({
            "q": f"{query} repo:{repo} state:{state}",
            "per_page": max_results,
        })
        data = self._get(f"/search/issues?{qs}")
        if isinstance(data, dict):
            items = data.get("items", [])
            return items if isinstance(items, list) else []
        return []

    def get_linked_pull_requests(
        self,
        repo: str,
        issue_number: int,
    ) -> list[dict[str, Any]]:
        """Search for PRs that reference this issue number."""
        qs = urllib.parse.urlencode({
            "q": f"is:pr repo:{repo} #{issue_number}",
            "per_page": 10,
        })
        data = self._get(f"/search/issues?{qs}")
        if isinstance(data, dict):
            items = data.get("items", [])
            return items if isinstance(items, list) else []
        return []

    def get_pr_files(self, repo: str, number: int) -> list[dict[str, Any]]:
        """Return the list of files changed in a pull request."""
        data = self._get(f"/repos/{repo}/pulls/{number}/files")
        return data if isinstance(data, list) else []

    def get_pr_reviews(self, repo: str, number: int) -> list[dict[str, Any]]:
        """Return submitted reviews on a pull request."""
        data = self._get(f"/repos/{repo}/pulls/{number}/reviews")
        return data if isinstance(data, list) else []

    def get_pr_comments(self, repo: str, number: int) -> list[dict[str, Any]]:
        """Return inline review comments on a pull request."""
        data = self._get(f"/repos/{repo}/pulls/{number}/comments")
        return data if isinstance(data, list) else []

    def get_workflow_run_logs(self, repo: str, run_id: int) -> str:
        """Fetch the log text for a workflow run (first 50 KB).

        Returns an empty string when the logs are unavailable or the token
        lacks the ``actions:read`` scope.
        """
        try:
            url = self._base_url + f"/repos/{repo}/actions/runs/{run_id}/logs"
            self._rate_limiter.acquire()
            req = urllib.request.Request(url, headers=self._auth_headers())
            with urllib.request.urlopen(req) as resp:
                self._sync_rate_limit(dict(resp.headers))
                raw: bytes = resp.read(50_000)
                return raw.decode("utf-8", errors="replace")
        except Exception:
            return ""

    def get_check_run_details(self, repo: str, check_run_id: int) -> dict[str, Any]:
        """Return details for a single check run."""
        result: dict[str, Any] = self._get(f"/repos/{repo}/check-runs/{check_run_id}")
        return result

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

    def create_pr_review(
        self,
        repo: str,
        pr_number: int,
        body: str,
        inline_comments: list[dict[str, Any]],
        commit_id: str,
        decision: Decision,
    ) -> None:
        """Post a PR review with optional inline comments (COMMENT event, non-approving)."""
        self._check_write_allowed(decision)
        self._post(
            f"/repos/{repo}/pulls/{pr_number}/reviews",
            {
                "commit_id": commit_id,
                "body": body,
                "event": "COMMENT",
                "comments": inline_comments,
            },
        )

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
