"""Tests for providers/claude.py — SDK mapping and error translation.

The ``anthropic`` package is injected via sys.modules so these tests run
without the real SDK installed.
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from repoheart.providers.base import (
    CompletionRequest,
    Message,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

# ---------------------------------------------------------------------------
# Helpers to build a fake anthropic module
# ---------------------------------------------------------------------------


def _make_fake_anthropic(response: MagicMock | None = None) -> ModuleType:
    """Return a minimal fake anthropic module."""
    fake = MagicMock()

    # Exception classes need to be real types so isinstance checks work.
    class RateLimitError(Exception):
        pass

    class AuthenticationError(Exception):
        pass

    class APITimeoutError(Exception):
        pass

    class APIStatusError(Exception):
        status_code: int = 500

        def __init__(self, msg: str, *, status_code: int = 500, response=None, body=None):
            super().__init__(msg)
            self.status_code = status_code

    fake.RateLimitError = RateLimitError
    fake.AuthenticationError = AuthenticationError
    fake.APITimeoutError = APITimeoutError
    fake.APIStatusError = APIStatusError

    if response is not None:
        fake.Anthropic.return_value.messages.create.return_value = response

    return fake


def _make_response(content: str = "claude says hi") -> MagicMock:
    resp = MagicMock()
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = content
    resp.content = [text_block]
    resp.stop_reason = "end_turn"
    resp.model = "claude-test"
    resp.usage.input_tokens = 8
    resp.usage.output_tokens = 4
    return resp


def _req(content: str = "hi") -> CompletionRequest:
    return CompletionRequest(
        messages=[Message(role="user", content=content)],
        model="claude-test",
    )


@pytest.fixture()
def fake_anthropic() -> MagicMock:
    return _make_fake_anthropic(_make_response())


# ---------------------------------------------------------------------------
# Successful completion
# ---------------------------------------------------------------------------


def test_complete_returns_content(fake_anthropic: MagicMock) -> None:
    with patch.dict(sys.modules, {"anthropic": fake_anthropic}):
        # Force reimport
        if "repoheart.providers.claude" in sys.modules:
            del sys.modules["repoheart.providers.claude"]
        from repoheart.providers.claude import ClaudeProvider

        p = ClaudeProvider("claude-test", api_key="k")
        resp = p.complete(_req())

    assert resp.content == "claude says hi"
    assert resp.model == "claude-test"
    assert resp.input_tokens == 8
    assert resp.output_tokens == 4
    assert resp.finish_reason == "end_turn"


def test_supports_tools_true(fake_anthropic: MagicMock) -> None:
    with patch.dict(sys.modules, {"anthropic": fake_anthropic}):
        if "repoheart.providers.claude" in sys.modules:
            del sys.modules["repoheart.providers.claude"]
        from repoheart.providers.claude import ClaudeProvider

        assert ClaudeProvider("m", api_key="k").supports_tools() is True


def test_provider_name(fake_anthropic: MagicMock) -> None:
    with patch.dict(sys.modules, {"anthropic": fake_anthropic}):
        if "repoheart.providers.claude" in sys.modules:
            del sys.modules["repoheart.providers.claude"]
        from repoheart.providers.claude import ClaudeProvider

        assert ClaudeProvider("m", api_key="k").provider_name() == "claude"


def test_system_prompt_passed_as_kwarg(fake_anthropic: MagicMock) -> None:
    with patch.dict(sys.modules, {"anthropic": fake_anthropic}):
        if "repoheart.providers.claude" in sys.modules:
            del sys.modules["repoheart.providers.claude"]
        from repoheart.providers.claude import ClaudeProvider

        p = ClaudeProvider("m", api_key="k")
        req = CompletionRequest(
            messages=[Message("user", "q")],
            model="m",
            system="Be terse.",
        )
        p.complete(req)

    call_kwargs = fake_anthropic.Anthropic.return_value.messages.create.call_args[1]
    assert call_kwargs.get("system") == "Be terse."


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


def _error_test(exc_class_name: str, expected: type) -> None:
    fake = _make_fake_anthropic()
    exc_class = getattr(fake, exc_class_name)

    if exc_class_name == "APIStatusError":
        fake.Anthropic.return_value.messages.create.side_effect = exc_class(
            "err", status_code=500
        )
    else:
        fake.Anthropic.return_value.messages.create.side_effect = exc_class("err")

    with patch.dict(sys.modules, {"anthropic": fake}):
        if "repoheart.providers.claude" in sys.modules:
            del sys.modules["repoheart.providers.claude"]
        from repoheart.providers.claude import ClaudeProvider

        p = ClaudeProvider("m", api_key="k", max_retries=0)
        with pytest.raises(expected):
            p.complete(_req())


def test_rate_limit_error() -> None:
    _error_test("RateLimitError", ProviderRateLimitError)


def test_auth_error() -> None:
    _error_test("AuthenticationError", ProviderAuthError)


def test_timeout_error() -> None:
    _error_test("APITimeoutError", ProviderTimeoutError)


def test_server_error_5xx() -> None:
    _error_test("APIStatusError", ProviderUnavailableError)


# ---------------------------------------------------------------------------
# Missing SDK
# ---------------------------------------------------------------------------


def test_missing_sdk_raises_provider_error() -> None:
    saved = sys.modules.pop("anthropic", None)
    try:
        if "repoheart.providers.claude" in sys.modules:
            del sys.modules["repoheart.providers.claude"]

        original = __import__

        def _no_anthropic(name: str, *args, **kwargs):
            if name == "anthropic":
                raise ImportError("No module named 'anthropic'")
            return original(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_no_anthropic):
            from repoheart.providers.claude import ClaudeProvider

            with pytest.raises(ProviderError, match="repoheart\\[claude\\]"):
                ClaudeProvider("m")
    finally:
        if saved is not None:
            sys.modules["anthropic"] = saved
