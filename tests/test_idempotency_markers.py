"""Tests for repoheart.idempotency.markers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from repoheart.github_ops.client import PermissionDenied
from repoheart.idempotency.markers import IdempotencyMarkers
from repoheart.observability.logger import StructuredLogger
from repoheart.safety.policy import Decision

_FINGERPRINT = "a" * 64
_MARKER = f"<!-- repoheart:fingerprint:{_FINGERPRINT} -->"


def _make_markers(token: str = "tok", comments: list[dict] | None = None) -> IdempotencyMarkers:
    mock_client = MagicMock()
    mock_client._token = token
    mock_client.get_issue_comments.return_value = comments or []
    return IdempotencyMarkers(client=mock_client, logger=StructuredLogger())


def test_extract_fingerprint_from_valid_comment() -> None:
    markers = _make_markers()
    fp = markers.extract_fingerprint_from_comment(_MARKER)
    assert fp == _FINGERPRINT


def test_extract_fingerprint_returns_none_for_plain_comment() -> None:
    markers = _make_markers()
    assert markers.extract_fingerprint_from_comment("Just a normal comment.") is None


def test_extract_fingerprint_returns_none_for_empty_string() -> None:
    markers = _make_markers()
    assert markers.extract_fingerprint_from_comment("") is None


def test_extract_fingerprint_partial_marker_returns_none() -> None:
    markers = _make_markers()
    assert markers.extract_fingerprint_from_comment("<!-- repoheart:fingerprint:short -->") is None


def test_has_been_processed_true_when_matching_comment() -> None:
    markers = _make_markers(comments=[{"body": _MARKER}])
    assert markers.has_been_processed("org/repo", 42, _FINGERPRINT) is True


def test_has_been_processed_false_when_no_matching_comment() -> None:
    markers = _make_markers(comments=[{"body": "no marker here"}])
    assert markers.has_been_processed("org/repo", 42, _FINGERPRINT) is False


def test_has_been_processed_false_when_no_token() -> None:
    markers = _make_markers(token="")
    assert markers.has_been_processed("org/repo", 42, _FINGERPRINT) is False


def test_has_been_processed_false_on_api_error() -> None:
    mock_client = MagicMock()
    mock_client._token = "tok"
    mock_client.get_issue_comments.side_effect = Exception("API error")
    markers = IdempotencyMarkers(client=mock_client, logger=StructuredLogger())
    assert markers.has_been_processed("org/repo", 42, _FINGERPRINT) is False


def test_record_processed_with_allow_posts_comment() -> None:
    mock_client = MagicMock()
    mock_client._token = "tok"
    markers = IdempotencyMarkers(client=mock_client, logger=StructuredLogger())
    markers.record_processed("org/repo", 42, _FINGERPRINT, "repoheart:triaged", Decision.ALLOW)
    mock_client.post_comment.assert_called_once()
    call_args = mock_client.post_comment.call_args
    assert _FINGERPRINT in call_args[0][2]  # body contains fingerprint


def test_record_processed_with_deny_raises_permission_denied() -> None:
    mock_client = MagicMock()
    mock_client._token = "tok"
    mock_client.post_comment.side_effect = PermissionDenied("denied")
    markers = IdempotencyMarkers(client=mock_client, logger=StructuredLogger())
    with pytest.raises(PermissionDenied):
        markers.record_processed("org/repo", 42, _FINGERPRINT, "label", Decision.DENY)
