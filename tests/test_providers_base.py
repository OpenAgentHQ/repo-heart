"""Tests for providers/base.py — structural invariants."""

from __future__ import annotations

import pytest

from repoheart.providers.base import (
    CompletionRequest,
    CompletionResponse,
    Message,
    Provider,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ToolCall,
    ToolDefinition,
    _retry_with_backoff,
)

# ---------------------------------------------------------------------------
# Dataclass immutability
# ---------------------------------------------------------------------------


def test_message_is_frozen() -> None:
    msg = Message(role="user", content="hello")
    with pytest.raises((AttributeError, TypeError)):
        msg.content = "world"  # type: ignore[misc]


def test_completion_request_is_frozen() -> None:
    req = CompletionRequest(messages=[Message("user", "hi")], model="m")
    with pytest.raises((AttributeError, TypeError)):
        req.model = "other"  # type: ignore[misc]


def test_completion_response_is_frozen() -> None:
    resp = CompletionResponse(content="ok")
    with pytest.raises((AttributeError, TypeError)):
        resp.content = "bad"  # type: ignore[misc]


def test_tool_definition_is_frozen() -> None:
    td = ToolDefinition(name="fn", description="d", parameters={})
    with pytest.raises((AttributeError, TypeError)):
        td.name = "x"  # type: ignore[misc]


def test_tool_call_is_frozen() -> None:
    tc = ToolCall(id="1", name="fn", arguments={})
    with pytest.raises((AttributeError, TypeError)):
        tc.id = "2"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


def test_completion_request_defaults() -> None:
    req = CompletionRequest(messages=[], model="m")
    assert req.tools == []
    assert req.max_tokens == 4096
    assert req.temperature == 0.0
    assert req.system == ""
    assert req.metadata == {}


def test_completion_response_defaults() -> None:
    resp = CompletionResponse(content="hi")
    assert resp.tool_calls == []
    assert resp.model == ""
    assert resp.input_tokens == 0
    assert resp.output_tokens == 0
    assert resp.finish_reason == "stop"


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


def test_provider_error_is_runtime_error() -> None:
    assert issubclass(ProviderError, RuntimeError)


def test_timeout_is_provider_error() -> None:
    assert issubclass(ProviderTimeoutError, ProviderError)


def test_rate_limit_is_provider_error() -> None:
    assert issubclass(ProviderRateLimitError, ProviderError)


def test_auth_is_provider_error() -> None:
    assert issubclass(ProviderAuthError, ProviderError)


def test_unavailable_is_provider_error() -> None:
    assert issubclass(ProviderUnavailableError, ProviderError)


# ---------------------------------------------------------------------------
# Provider ABC
# ---------------------------------------------------------------------------


def test_provider_is_abstract() -> None:
    with pytest.raises(TypeError):
        Provider()  # type: ignore[abstract]


def test_provider_name_defaults_to_class_name() -> None:
    class MyProvider(Provider):
        def complete(self, req):  # type: ignore[override]
            ...

        def supports_tools(self) -> bool:
            return False

    assert MyProvider().provider_name() == "MyProvider"


# ---------------------------------------------------------------------------
# _retry_with_backoff
# ---------------------------------------------------------------------------


def test_retry_succeeds_on_first_try() -> None:
    calls: list[int] = []

    def fn() -> int:
        calls.append(1)
        return 42

    result = _retry_with_backoff(fn, max_retries=3, exceptions=(ValueError,))
    assert result == 42
    assert len(calls) == 1


def test_retry_retries_on_matching_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    monkeypatch.setattr("random.uniform", lambda a, b: 0.0)

    attempt = 0

    def fn() -> str:
        nonlocal attempt
        attempt += 1
        if attempt < 3:
            raise ValueError("transient")
        return "ok"

    result = _retry_with_backoff(fn, max_retries=5, exceptions=(ValueError,))
    assert result == "ok"
    assert attempt == 3


def test_retry_raises_after_exhaustion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    monkeypatch.setattr("random.uniform", lambda a, b: 0.0)

    def fn() -> None:
        raise ValueError("always")

    with pytest.raises(ValueError, match="always"):
        _retry_with_backoff(fn, max_retries=2, exceptions=(ValueError,))


def test_retry_does_not_catch_unmatched_exception() -> None:
    def fn() -> None:
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError, match="nope"):
        _retry_with_backoff(fn, max_retries=3, exceptions=(ValueError,))
