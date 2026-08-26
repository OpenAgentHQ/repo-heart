"""Tests for providers/openrouter.py — HTTP serialisation and error mapping."""

from __future__ import annotations

import io
import json
import os
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from repoheart.providers.base import (
    CompletionRequest,
    Message,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from repoheart.providers.openrouter import OpenRouterProvider


def _provider() -> OpenRouterProvider:
    return OpenRouterProvider("test-model", api_key="test-key", max_retries=0)


def _req(content: str = "hello") -> CompletionRequest:
    return CompletionRequest(
        messages=[Message(role="user", content=content)],
        model="test-model",
    )


def _openrouter_response(content: str = "response text") -> dict:
    return {
        "choices": [
            {
                "message": {"content": content, "tool_calls": []},
                "finish_reason": "stop",
            }
        ],
        "model": "test-model",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


# ---------------------------------------------------------------------------
# Successful completion
# ---------------------------------------------------------------------------


def test_complete_returns_content() -> None:
    provider = _provider()
    resp_data = _openrouter_response("hello world")
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__ = lambda s: io.BytesIO(json.dumps(resp_data).encode())
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        resp = provider.complete(_req())
    assert resp.content == "hello world"
    assert resp.model == "test-model"
    assert resp.input_tokens == 10
    assert resp.output_tokens == 5
    assert resp.finish_reason == "stop"


def test_complete_serializes_system_prompt() -> None:
    provider = _provider()
    captured: list[dict] = []

    def fake_urlopen(req, timeout=None):
        body = json.loads(req.data.decode())
        captured.append(body)
        cm = MagicMock()
        cm.__enter__ = lambda s: io.BytesIO(json.dumps(_openrouter_response()).encode())
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        req = CompletionRequest(
            messages=[Message("user", "hi")],
            model="m",
            system="You are helpful.",
        )
        provider.complete(req)

    messages = captured[0]["messages"]
    assert messages[0] == {"role": "system", "content": "You are helpful."}
    assert messages[1] == {"role": "user", "content": "hi"}


def test_supports_tools_true() -> None:
    assert _provider().supports_tools() is True


def test_provider_name() -> None:
    assert _provider().provider_name() == "openrouter"


# ---------------------------------------------------------------------------
# Auth / missing key
# ---------------------------------------------------------------------------


def test_missing_api_key_raises_auth_error() -> None:
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("OPENROUTER_API_KEY", None)
        with pytest.raises(ProviderAuthError, match="OPENROUTER_API_KEY"):
            OpenRouterProvider("model")


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url="", code=code, msg=str(code), hdrs=None, fp=None)  # type: ignore[arg-type]


def test_429_raises_rate_limit_error() -> None:
    provider = _provider()
    with patch("urllib.request.urlopen", side_effect=_http_error(429)), pytest.raises(
        ProviderRateLimitError
    ):
        provider.complete(_req())


def test_401_raises_auth_error() -> None:
    provider = _provider()
    with patch("urllib.request.urlopen", side_effect=_http_error(401)), pytest.raises(
        ProviderAuthError
    ):
        provider.complete(_req())


def test_403_raises_auth_error() -> None:
    provider = _provider()
    with patch("urllib.request.urlopen", side_effect=_http_error(403)), pytest.raises(
        ProviderAuthError
    ):
        provider.complete(_req())


def test_503_raises_unavailable_error() -> None:
    provider = _provider()
    with patch("urllib.request.urlopen", side_effect=_http_error(503)), pytest.raises(
        ProviderUnavailableError
    ):
        provider.complete(_req())


def test_timeout_raises_timeout_error() -> None:
    provider = _provider()
    with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")), pytest.raises(
        ProviderTimeoutError
    ):
        provider.complete(_req())


def test_url_error_with_timeout_string_raises_timeout_error() -> None:
    provider = _provider()
    exc = urllib.error.URLError("timed out")
    with patch("urllib.request.urlopen", side_effect=exc), pytest.raises(ProviderTimeoutError):
        provider.complete(_req())


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


def test_retries_on_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    monkeypatch.setattr("random.uniform", lambda a, b: 0.0)

    provider = OpenRouterProvider("m", api_key="k", max_retries=3)
    call_count = 0

    def fake_urlopen(req, timeout=None):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise _http_error(429)
        cm = MagicMock()
        cm.__enter__ = lambda s: io.BytesIO(json.dumps(_openrouter_response("ok")).encode())
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        resp = provider.complete(_req())

    assert resp.content == "ok"
    assert call_count == 3
