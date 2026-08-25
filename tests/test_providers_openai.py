"""Tests for providers/openai.py — SDK mapping and error translation.

The ``openai`` package is injected via sys.modules so these tests run
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
# Helpers to build a fake openai module
# ---------------------------------------------------------------------------


def _make_fake_openai(response: MagicMock | None = None) -> ModuleType:
    fake = MagicMock()

    class RateLimitError(Exception):
        pass

    class AuthenticationError(Exception):
        pass

    class APITimeoutError(Exception):
        pass

    class APIStatusError(Exception):
        def __init__(self, msg: str, *, status_code: int = 500, response=None, body=None):
            super().__init__(msg)
            self.status_code = status_code

    fake.RateLimitError = RateLimitError
    fake.AuthenticationError = AuthenticationError
    fake.APITimeoutError = APITimeoutError
    fake.APIStatusError = APIStatusError

    if response is not None:
        fake.OpenAI.return_value.chat.completions.create.return_value = response

    return fake


def _make_response(content: str = "openai says hi") -> MagicMock:
    resp = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = []
    choice.finish_reason = "stop"
    resp.choices = [choice]
    resp.model = "gpt-test"
    resp.usage.prompt_tokens = 6
    resp.usage.completion_tokens = 3
    return resp


def _req(content: str = "hi") -> CompletionRequest:
    return CompletionRequest(
        messages=[Message(role="user", content=content)],
        model="gpt-test",
    )


@pytest.fixture()
def fake_openai() -> MagicMock:
    return _make_fake_openai(_make_response())


# ---------------------------------------------------------------------------
# Successful completion
# ---------------------------------------------------------------------------


def test_complete_returns_content(fake_openai: MagicMock) -> None:
    with patch.dict(sys.modules, {"openai": fake_openai}):
        if "repoheart.providers.openai" in sys.modules:
            del sys.modules["repoheart.providers.openai"]
        from repoheart.providers.openai import OpenAIProvider

        p = OpenAIProvider("gpt-test", api_key="k")
        resp = p.complete(_req())

    assert resp.content == "openai says hi"
    assert resp.model == "gpt-test"
    assert resp.input_tokens == 6
    assert resp.output_tokens == 3
    assert resp.finish_reason == "stop"


def test_system_prepended_as_message(fake_openai: MagicMock) -> None:
    with patch.dict(sys.modules, {"openai": fake_openai}):
        if "repoheart.providers.openai" in sys.modules:
            del sys.modules["repoheart.providers.openai"]
        from repoheart.providers.openai import OpenAIProvider

        p = OpenAIProvider("m", api_key="k")
        req = CompletionRequest(
            messages=[Message("user", "q")],
            model="m",
            system="Be brief.",
        )
        p.complete(req)

    call_kwargs = fake_openai.OpenAI.return_value.chat.completions.create.call_args[1]
    messages = call_kwargs["messages"]
    assert messages[0] == {"role": "system", "content": "Be brief."}
    assert messages[1] == {"role": "user", "content": "q"}


def test_supports_tools_true(fake_openai: MagicMock) -> None:
    with patch.dict(sys.modules, {"openai": fake_openai}):
        if "repoheart.providers.openai" in sys.modules:
            del sys.modules["repoheart.providers.openai"]
        from repoheart.providers.openai import OpenAIProvider

        assert OpenAIProvider("m", api_key="k").supports_tools() is True


def test_provider_name(fake_openai: MagicMock) -> None:
    with patch.dict(sys.modules, {"openai": fake_openai}):
        if "repoheart.providers.openai" in sys.modules:
            del sys.modules["repoheart.providers.openai"]
        from repoheart.providers.openai import OpenAIProvider

        assert OpenAIProvider("m", api_key="k").provider_name() == "openai"


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


def _error_test(exc_class_name: str, expected: type) -> None:
    fake = _make_fake_openai()
    exc_class = getattr(fake, exc_class_name)

    if exc_class_name == "APIStatusError":
        fake.OpenAI.return_value.chat.completions.create.side_effect = exc_class(
            "err", status_code=503
        )
    else:
        fake.OpenAI.return_value.chat.completions.create.side_effect = exc_class("err")

    with patch.dict(sys.modules, {"openai": fake}):
        if "repoheart.providers.openai" in sys.modules:
            del sys.modules["repoheart.providers.openai"]
        from repoheart.providers.openai import OpenAIProvider

        p = OpenAIProvider("m", api_key="k", max_retries=0)
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
    saved = sys.modules.pop("openai", None)
    try:
        if "repoheart.providers.openai" in sys.modules:
            del sys.modules["repoheart.providers.openai"]

        original = __import__

        def _no_openai(name: str, *args, **kwargs):
            if name == "openai":
                raise ImportError("No module named 'openai'")
            return original(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_no_openai):
            from repoheart.providers.openai import OpenAIProvider

            with pytest.raises(ProviderError, match="repoheart\\[openai\\]"):
                OpenAIProvider("m")
    finally:
        if saved is not None:
            sys.modules["openai"] = saved
