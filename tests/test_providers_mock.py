"""Tests for providers/mock.py — MockProvider contract."""

from __future__ import annotations

import pytest

from repoheart.providers.base import (
    CompletionRequest,
    Message,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from repoheart.providers.mock import CannedResponse, MockProvider


def _req(*messages: str) -> CompletionRequest:
    return CompletionRequest(
        messages=[Message(role="user", content=m) for m in messages],
        model="mock-model",
    )


# ---------------------------------------------------------------------------
# Basic behaviour
# ---------------------------------------------------------------------------


def test_returns_default_response() -> None:
    mock = MockProvider(default_response=CannedResponse("hello"))
    resp = mock.complete(_req("anything"))
    assert resp.content == "hello"
    assert resp.model == "mock"


def test_keyed_lookup_takes_precedence() -> None:
    mock = MockProvider(
        responses={"specific": CannedResponse("targeted")},
        default_response=CannedResponse("fallback"),
    )
    assert mock.complete(_req("specific")).content == "targeted"
    assert mock.complete(_req("other")).content == "fallback"


def test_key_is_last_message_content() -> None:
    mock = MockProvider(
        responses={"second": CannedResponse("matched")},
        default_response=CannedResponse("no"),
    )
    req = CompletionRequest(
        messages=[Message("user", "first"), Message("user", "second")],
        model="m",
    )
    assert mock.complete(req).content == "matched"


def test_no_default_no_key_raises_provider_error() -> None:
    mock = MockProvider()
    with pytest.raises(ProviderError):
        mock.complete(_req("unmatched"))


# ---------------------------------------------------------------------------
# call_count
# ---------------------------------------------------------------------------


def test_call_count_increments() -> None:
    mock = MockProvider(default_response=CannedResponse("ok"))
    assert mock.call_count == 0
    mock.complete(_req("a"))
    mock.complete(_req("b"))
    assert mock.call_count == 2


def test_call_count_increments_even_on_raise() -> None:
    mock = MockProvider(raise_on_complete=ProviderRateLimitError)
    with pytest.raises(ProviderRateLimitError):
        mock.complete(_req("x"))
    assert mock.call_count == 1


# ---------------------------------------------------------------------------
# raise_on_complete
# ---------------------------------------------------------------------------


def test_raises_configured_error() -> None:
    mock = MockProvider(raise_on_complete=ProviderTimeoutError)
    with pytest.raises(ProviderTimeoutError):
        mock.complete(_req("hi"))


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_identical_requests_produce_identical_responses() -> None:
    mock = MockProvider(default_response=CannedResponse("fixed"))
    r1 = mock.complete(_req("q"))
    r2 = mock.complete(_req("q"))
    assert r1.content == r2.content
    assert r1.finish_reason == r2.finish_reason


# ---------------------------------------------------------------------------
# supports_tools
# ---------------------------------------------------------------------------


def test_supports_tools_returns_true() -> None:
    assert MockProvider().supports_tools() is True


def test_provider_name() -> None:
    assert MockProvider().provider_name() == "mock"
