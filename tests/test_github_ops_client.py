"""Tests for repoheart.github_ops.client."""

from __future__ import annotations

import json
import urllib.error
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from repoheart.github_ops.budgeter import RateLimiter
from repoheart.github_ops.client import GitHubClient, GitHubError, PermissionDenied
from repoheart.observability.logger import StructuredLogger
from repoheart.safety.policy import Decision


def _make_client(token: str = "test-token") -> GitHubClient:
    return GitHubClient(
        token=token,
        rate_limiter=RateLimiter(capacity=5000),
        logger=StructuredLogger(),
        base_url="https://api.github.com",
    )


def _mock_response(
    body: Any, status: int = 200, headers: dict[str, str] | None = None
) -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = json.dumps(body).encode("utf-8")
    resp.headers = headers or {}
    resp.status = status
    resp.__enter__.return_value = resp  # context manager returns self
    resp.__exit__.return_value = False
    return resp


# ── Permission guard ──────────────────────────────────────────────────────────

def test_add_label_with_deny_raises_permission_denied() -> None:
    client = _make_client()
    with pytest.raises(PermissionDenied):
        client.add_label("org/repo", 1, ["bug"], Decision.DENY)


def test_add_label_with_escalate_raises_permission_denied() -> None:
    client = _make_client()
    with pytest.raises(PermissionDenied):
        client.add_label("org/repo", 1, ["bug"], Decision.ESCALATE)


def test_post_comment_with_deny_raises_permission_denied() -> None:
    client = _make_client()
    with pytest.raises(PermissionDenied):
        client.post_comment("org/repo", 1, "hello", Decision.DENY)


def test_create_label_with_deny_raises_permission_denied() -> None:
    client = _make_client()
    with pytest.raises(PermissionDenied):
        client.create_label("org/repo", "bug", "ff0000", Decision.DENY)


# ── HTTP error handling ───────────────────────────────────────────────────────

def test_get_404_raises_github_error() -> None:
    client = _make_client()
    http_error = urllib.error.HTTPError(
        url="https://api.github.com/repos/org/repo/issues/99",
        code=404,
        msg="Not Found",
        hdrs=MagicMock(),  # type: ignore[arg-type]
        fp=None,
    )
    with (
        patch("urllib.request.urlopen", side_effect=http_error),
        pytest.raises(GitHubError, match="404"),
    ):
        client.get_issue("org/repo", 99)


# ── Rate limiter integration ──────────────────────────────────────────────────

def test_rate_limiter_acquire_called_before_get() -> None:
    client = _make_client()
    mock_response = _mock_response({"number": 1})
    with (
        patch("urllib.request.urlopen", return_value=mock_response),
        patch.object(client._rate_limiter, "acquire") as mock_acquire,
    ):
        client.get_issue("org/repo", 1)
        mock_acquire.assert_called_once()


def test_rate_limiter_acquire_called_before_post() -> None:
    client = _make_client()
    mock_response = _mock_response({})
    with (
        patch("urllib.request.urlopen", return_value=mock_response),
        patch.object(client._rate_limiter, "acquire") as mock_acquire,
    ):
        client.add_label("org/repo", 1, ["bug"], Decision.ALLOW)
        mock_acquire.assert_called_once()


def test_headers_synced_after_response() -> None:
    client = _make_client()
    headers = {"X-RateLimit-Remaining": "4998"}
    mock_response = _mock_response({"number": 1}, headers=headers)
    with patch("urllib.request.urlopen", return_value=mock_response):
        client.get_issue("org/repo", 1)
    assert client._rate_limiter.snapshot().remaining == 4998


# ── Successful write ──────────────────────────────────────────────────────────

def test_add_label_with_allow_succeeds() -> None:
    client = _make_client()
    mock_response = _mock_response([])
    with patch("urllib.request.urlopen", return_value=mock_response):
        client.add_label("org/repo", 1, ["bug"], Decision.ALLOW)


def test_post_comment_with_allow_succeeds() -> None:
    client = _make_client()
    mock_response = _mock_response({})
    with patch("urllib.request.urlopen", return_value=mock_response):
        client.post_comment("org/repo", 1, "test comment", Decision.ALLOW)


# ── Read operations ───────────────────────────────────────────────────────────

def test_list_issue_labels_returns_names() -> None:
    client = _make_client()
    label_data = [{"name": "bug"}, {"name": "enhancement"}]
    mock_response = _mock_response(label_data)
    with patch("urllib.request.urlopen", return_value=mock_response):
        labels = client.list_issue_labels("org/repo", 1)
    assert labels == ["bug", "enhancement"]


def test_get_issue_comments_returns_list() -> None:
    client = _make_client()
    comments = [{"id": 1, "body": "hello"}]
    mock_response = _mock_response(comments)
    with patch("urllib.request.urlopen", return_value=mock_response):
        result = client.get_issue_comments("org/repo", 1)
    assert result == comments
